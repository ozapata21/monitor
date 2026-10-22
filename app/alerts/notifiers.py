import asyncio
import logging
import smtplib
from email.message import EmailMessage
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Protocol

import httpx

from app.core.config import settings
from app.correlation.engine import AlertEvent
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert

logger = logging.getLogger(__name__)


def _email_delivery_logger() -> logging.Logger:
    log_path = Path(settings.EMAIL_LOG_FILE).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    delivery_logger = logging.getLogger("app.email_delivery")
    delivery_logger.setLevel(logging.INFO)
    delivery_logger.propagate = False
    if not any(
        getattr(handler, "baseFilename", None) == str(log_path)
        for handler in delivery_logger.handlers
    ):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=settings.EMAIL_LOG_MAX_BYTES,
            backupCount=settings.EMAIL_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        delivery_logger.addHandler(handler)
    return delivery_logger


class Notifier(Protocol):
    async def send(self, event: AlertEvent) -> None: ...


class WebhookNotifier:
    def __init__(self, url: str, timeout: float = 5.0):
        self._url = url
        self._timeout = timeout

    async def send(self, event: AlertEvent) -> None:
        payload = {
            "device_id": event.device_id,
            "hostname": event.hostname,
            "kind": event.kind.value,
            "message": event.message,
            "root_cause_id": event.root_cause_id,
            "timestamp": event.timestamp.isoformat(),
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            (await client.post(self._url, json=payload)).raise_for_status()


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 5.0):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._timeout = timeout

    async def send(self, event: AlertEvent) -> None:
        text = f"[{event.kind.value}] {event.message}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            (await client.post(self._url, json={"chat_id": self._chat_id, "text": text})).raise_for_status()


class EmailNotifier:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipient: str,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: float = 10.0,
    ):
        self._host = host
        self._port = port
        self._sender = sender
        self._recipient = recipient
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._use_ssl = use_ssl
        self._timeout = timeout

    async def send(self, event: AlertEvent) -> None:
        if not event.email_notifications_enabled:
            _email_delivery_logger().info(
                "status=SUPPRESSED kind=%r device_id=%r hostname=%r recipient=%r",
                event.kind.value,
                event.device_id,
                event.hostname,
                self._recipient,
            )
            return
        try:
            await asyncio.to_thread(self._send_sync, event)
        except Exception as exc:
            _email_delivery_logger().error(
                "status=FAILED kind=%r device_id=%r hostname=%r recipient=%r "
                "error_type=%s error=%r",
                event.kind.value,
                event.device_id,
                event.hostname,
                self._recipient,
                type(exc).__name__,
                str(exc)[:500],
            )
            raise
        _email_delivery_logger().info(
            "status=ACCEPTED_BY_SMTP kind=%r device_id=%r hostname=%r recipient=%r",
            event.kind.value,
            event.device_id,
            event.hostname,
            self._recipient,
        )

    def _send_sync(self, event: AlertEvent) -> None:
        message = EmailMessage()
        message["Subject"] = f"[NOC] {event.kind.value}: {event.hostname}"
        message["From"] = self._sender
        message["To"] = self._recipient
        message.set_content(
            f"Alerta: {event.kind.value}\n"
            f"Dispositivo: {event.hostname}\n"
            f"Device ID: {event.device_id}\n"
            f"Mensaje: {event.message}\n"
            f"Fecha: {event.timestamp.isoformat()}\n"
            f"Causa raíz: {event.root_cause_id or 'N/A'}\n"
        )

        smtp_class = smtplib.SMTP_SSL if self._use_ssl else smtplib.SMTP
        with smtp_class(self._host, self._port, timeout=self._timeout) as server:
            if self._use_tls and not self._use_ssl:
                server.starttls()
            if self._username and self._password:
                server.login(self._username, self._password)
            server.send_message(message)


def notifiers_from_settings() -> list[Notifier]:
    result: list[Notifier] = []
    if settings.WEBHOOK_URL:
        result.append(WebhookNotifier(settings.WEBHOOK_URL))
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        result.append(TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID))
    email_configured = (settings.SMTP_HOST, settings.SMTP_FROM, settings.ALERT_EMAIL_TO)
    if all(email_configured):
        if bool(settings.SMTP_USERNAME) != bool(settings.SMTP_PASSWORD):
            logger.warning("Notificador de correo desactivado: faltan credenciales SMTP completas")
        else:
            result.append(EmailNotifier(
                host=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                sender=settings.SMTP_FROM,
                recipient=settings.ALERT_EMAIL_TO,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                use_tls=settings.SMTP_USE_TLS,
                use_ssl=settings.SMTP_USE_SSL,
                timeout=settings.SMTP_TIMEOUT,
            ))
    elif any(email_configured):
        logger.warning("Notificador de correo desactivado: configura SMTP_HOST, SMTP_FROM y ALERT_EMAIL_TO")
    return result


class AlertDispatcher:
    """Persiste cada alerta y la envía a todos los notificadores sin bloquear el sondeo."""

    def __init__(self, notifiers: Optional[list[Notifier]] = None):
        self._notifiers = notifiers if notifiers is not None else notifiers_from_settings()
        self._pending: set[asyncio.Task] = set()

    def dispatch(self, events: list[AlertEvent]) -> None:
        for event in events:
            task = asyncio.create_task(self._handle(event))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def drain(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)

    async def _handle(self, event: AlertEvent) -> None:
        try:
            async with AsyncSessionLocal() as session:
                session.add(Alert(
                    timestamp=event.timestamp, device_id=event.device_id, kind=event.kind.value,
                    message=event.message, root_cause_id=event.root_cause_id,
                ))
                await session.commit()
        except Exception:
            logger.exception("No se pudo persistir la alerta")
        for notifier in self._notifiers:
            try:
                await notifier.send(event)
            except Exception as exc:
                # No registrar str(exc): httpx incluye la URL (token de Telegram)
                logger.error("Fallo en notificador %s: %s", type(notifier).__name__, type(exc).__name__)
