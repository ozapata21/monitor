import asyncio
import socket

import pytest
from sqlalchemy import func, select

from app.collector.buffer import MetricBuffer, MetricRecord
from app.collector.checks import check_icmp, check_rtsp
from app.collector.engine import CollectorEngine
from app.core.security import encrypt_credential
from app.db.session import AsyncSessionLocal, init_db
from app.models.device import Device, DeviceStatus, DeviceType
from app.models.metric import Metric


async def _make_device(**kw) -> Device:
    await init_db()
    device = Device(
        hostname=kw.pop("hostname", "DEV"),
        ip_address=kw.pop("ip_address", "127.0.0.1"),
        device_type=kw.pop("device_type", DeviceType.CAMERA),
        site_id="S1",
        **kw,
    )
    async with AsyncSessionLocal() as s:
        s.add(device)
        await s.commit()
    return device


async def _count(device_id: str, metric_type: str) -> int:
    async with AsyncSessionLocal() as s:
        q = select(func.count()).select_from(Metric).where(
            Metric.device_id == device_id, Metric.metric_type == metric_type
        )
        return (await s.execute(q)).scalar_one()


async def test_buffer_batch_flush_updates_status():
    dev = await _make_device()
    buf = MetricBuffer(batch_size=10)
    for i in range(25):
        buf.put(MetricRecord(dev.id, "T_BATCH", float(i), DeviceStatus.DOWN if i == 24 else None))
    assert await buf.flush() == 25
    assert await _count(dev.id, "T_BATCH") == 25
    async with AsyncSessionLocal() as s:
        assert (await s.get(Device, dev.id)).status == DeviceStatus.DOWN


async def test_rtsp_up_and_down():
    async def handler(reader, writer):
        await reader.readline()
        writer.write(b"RTSP/1.0 200 OK\r\n\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    dev = await _make_device(rtsp_url_encrypted=encrypt_credential(f"rtsp://u:p@127.0.0.1:{port}/s"))
    async with server:
        up = await check_rtsp(dev)
    assert up[0].status == DeviceStatus.UP
    down = await check_rtsp(dev)
    assert down[0].status == DeviceStatus.DOWN


async def test_icmp_localhost():
    dev = await _make_device()
    records = await check_icmp(dev, timeout=1, count=1)
    if records[0].status == DeviceStatus.DOWN and "error" in (records[0].detail or ""):
        pytest.skip("ICMP no permitido en este entorno")
    assert records[0].status == DeviceStatus.UP


async def test_engine_collects_syslog_and_polling():
    dev = await _make_device(ip_address="127.0.0.1", hostname="SYSLOG-DEV")

    async def fake_check(device):
        return [MetricRecord(device.id, "T_FAKE", 1.0, DeviceStatus.UP)]

    buf = MetricBuffer(flush_interval=0.1)
    engine = CollectorEngine(buffer=buf, check_fns=[fake_check], interval=0.1, syslog_port=0)
    # syslog_port=0 desactiva el receptor por defecto; usar puerto libre
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    engine._syslog_port = free_port
    await engine.start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(b"<11>link down on port 3", ("127.0.0.1", free_port))
    await asyncio.sleep(0.5)
    await engine.stop()
    assert await _count(dev.id, "T_FAKE") >= 1
    assert await _count(dev.id, "SYSLOG") >= 1
