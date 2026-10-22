from datetime import datetime

import pytest

from app.alerts import notifiers
from app.alerts.notifiers import AlertDispatcher, EmailNotifier
from app.correlation.engine import AlertEvent, AlertKind, CorrelationEngine
from app.db.session import AsyncSessionLocal, init_db
from app.models.alert import Alert
from app.models.device import Device, DeviceStatus, DeviceType

from sqlalchemy import create_engine, inspect, select, text

from app.db.session import _add_email_notifications_column

DOWN, UP = DeviceStatus.DOWN, DeviceStatus.UP


def _dev(id_, parent=None):
    return Device(id=id_, hostname=id_.upper(), ip_address="10.0.0.1",
                  device_type=DeviceType.SWITCH, site_id="S", parent_device_id=parent,
                  updated_at=datetime.utcnow())


def _engine(**kw):
    eng = CorrelationEngine(**kw)
    eng.set_topology([_dev("core"), _dev("sw", "core"), _dev("cam", "sw")])
    return eng


def test_parent_down_suppresses_children():
    eng = _engine()
    for d in ("core", "sw", "cam"):
        assert eng.process(d, UP, now=0) == []
    events = eng.process("core", DOWN, now=1)
    assert [e.kind for e in events] == [AlertKind.DOWN] and events[0].device_id == "core"
    assert eng.process("sw", DOWN, now=2) == []
    assert eng.process("cam", DOWN, now=2) == []
    # recuperación: el padre alerta, los hijos suprimidos no generan recovery
    assert [e.device_id for e in eng.process("core", UP, now=10)] == ["core"]
    assert eng.process("sw", UP, now=11) == []
    assert eng.process("cam", UP, now=11) == []


def test_child_still_down_after_parent_recovers_alerts():
    eng = _engine()
    for d in ("core", "sw", "cam"):
        eng.process(d, UP, now=0)
    eng.process("core", DOWN, now=1)
    eng.process("cam", DOWN, now=2)
    eng.process("core", UP, now=10)
    events = eng.process("cam", DOWN, now=11)
    assert [(e.kind, e.device_id) for e in events] == [(AlertKind.DOWN, "cam")]


def test_independent_child_down_alerts():
    eng = _engine()
    eng.process("cam", UP, now=0)
    assert [e.kind for e in eng.process("cam", DOWN, now=1)] == [AlertKind.DOWN]


def test_alert_event_inherits_device_email_preference():
    device = _dev("unstable-device")
    device.email_notifications_enabled = False
    eng = CorrelationEngine()
    eng.set_topology([device])

    event = eng.process(device.id, DOWN, now=1)[0]

    assert event.email_notifications_enabled is False


def test_email_notification_migration_upgrades_existing_sqlite_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id VARCHAR(36) PRIMARY KEY)"))
        _add_email_notifications_column(connection)
        columns = {column["name"] for column in inspect(connection).get_columns("devices")}
        assert "email_notifications_enabled" in columns
        connection.execute(text("INSERT INTO devices (id) VALUES ('legacy-device')"))
        value = connection.execute(text(
            "SELECT email_notifications_enabled FROM devices WHERE id = 'legacy-device'"
        )).scalar_one()
        assert value == 1


def test_flapping_window():
    eng = _engine(flap_threshold=4, flap_window=60)
    eng.process("cam", UP, now=0)
    kinds = []
    for i, st in enumerate([DOWN, UP, DOWN, UP, DOWN, UP], start=1):
        kinds += [e.kind for e in eng.process("cam", st, now=i)]
    assert kinds.count(AlertKind.FLAPPING) == 1
    assert kinds == [AlertKind.DOWN, AlertKind.RECOVERY, AlertKind.DOWN, AlertKind.FLAPPING]
    assert eng.tick(now=30) == []
    assert [e.kind for e in eng.tick(now=100)] == [AlertKind.FLAPPING_RESOLVED]


async def test_email_notifier_sends_message_with_tls_and_auth(monkeypatch, tmp_path):
    sent_messages = []
    smtp_calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            smtp_calls.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            smtp_calls.append("starttls")

        def login(self, username, password):
            smtp_calls.append(("login", username, password))

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(notifiers.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notifiers.settings, "EMAIL_LOG_FILE", str(tmp_path / "email.log"))
    notifier = EmailNotifier(
        host="smtp.example.com", port=587, sender="noc@example.com",
        recipient="admin@example.com", username="noc", password="secret",
    )
    event = AlertEvent(
        device_id="device-1", hostname="switch-01", kind=AlertKind.DOWN,
        message="El dispositivo está caído",
    )

    await notifier.send(event)

    assert smtp_calls == [
        ("smtp.example.com", 587, 10.0), "starttls", ("login", "noc", "secret"),
    ]
    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message["To"] == "admin@example.com"
    assert message["Subject"] == "[NOC] DOWN: switch-01"
    assert "Device ID: device-1" in message.get_content()
    log_contents = (tmp_path / "email.log").read_text()
    assert "status=ACCEPTED_BY_SMTP" in log_contents
    assert "device-1" in log_contents
    assert "secret" not in log_contents


async def test_email_notifier_skips_muted_device(monkeypatch, tmp_path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("SMTP no debe conectarse para un dispositivo silenciado")

    monkeypatch.setattr(notifiers.smtplib, "SMTP", fail_if_called)
    monkeypatch.setattr(notifiers.settings, "EMAIL_LOG_FILE", str(tmp_path / "email.log"))
    notifier = EmailNotifier(
        host="smtp.example.com", port=587, sender="noc@example.com",
        recipient="admin@example.com",
    )
    event = AlertEvent(
        device_id="device-muted", hostname="unstable-sensor", kind=AlertKind.DOWN,
        message="El dispositivo está caído", email_notifications_enabled=False,
    )

    await notifier.send(event)

    log_contents = (tmp_path / "email.log").read_text()
    assert "status=SUPPRESSED" in log_contents
    assert "device-muted" in log_contents


async def test_email_notifier_logs_smtp_failure_without_password(monkeypatch, tmp_path):
    class FailingSMTP:
        def __init__(self, host, port, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            raise notifiers.smtplib.SMTPAuthenticationError(535, b"authentication failed")

    monkeypatch.setattr(notifiers.smtplib, "SMTP", FailingSMTP)
    monkeypatch.setattr(notifiers.settings, "EMAIL_LOG_FILE", str(tmp_path / "email.log"))
    notifier = EmailNotifier(
        host="smtp.example.com", port=587, sender="noc@example.com",
        recipient="admin@example.com", username="noc", password="secret",
    )
    event = AlertEvent(
        device_id="device-2", hostname="switch-02", kind=AlertKind.DOWN,
        message="El dispositivo está caído",
    )

    with pytest.raises(notifiers.smtplib.SMTPAuthenticationError):
        await notifier.send(event)

    log_contents = (tmp_path / "email.log").read_text()
    assert "status=FAILED" in log_contents
    assert "SMTPAuthenticationError" in log_contents
    assert "535" in log_contents
    assert "device-2" in log_contents
    assert "secret" not in log_contents


def test_email_notifier_is_enabled_by_settings(monkeypatch):
    monkeypatch.setattr(notifiers.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(notifiers.settings, "SMTP_FROM", "noc@example.com")
    monkeypatch.setattr(notifiers.settings, "ALERT_EMAIL_TO", "admin@example.com")
    monkeypatch.setattr(notifiers.settings, "SMTP_USERNAME", "noc")
    monkeypatch.setattr(notifiers.settings, "SMTP_PASSWORD", "secret")

    configured = notifiers.notifiers_from_settings()

    assert any(isinstance(notifier, EmailNotifier) for notifier in configured)


async def test_dispatcher_persists_and_notifies():
    await init_db()
    async with AsyncSessionLocal() as s:
        dev = _dev("x-disp")
        dev.id = "x-disp-1"
        s.add(dev)
        await s.commit()

    sent = []

    class Fake:
        async def send(self, event):
            sent.append(event)

    class Boom:
        async def send(self, event):
            raise RuntimeError("fallo")

    eng = CorrelationEngine()
    eng.set_topology([dev])
    disp = AlertDispatcher([Boom(), Fake()])
    eng.process("x-disp-1", UP, now=0)
    disp.dispatch(eng.process("x-disp-1", DOWN, now=1))
    await disp.drain()
    assert len(sent) == 1
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Alert).where(Alert.device_id == "x-disp-1"))).scalars().all()
    assert [r.kind for r in rows] == ["DOWN"]
