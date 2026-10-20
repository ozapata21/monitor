import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from sqlalchemy import select

from app.alerts.notifiers import AlertDispatcher
from app.collector import checks
from app.collector.buffer import MetricBuffer, MetricRecord
from app.collector.syslog import start_syslog_server
from app.core.config import settings
from app.correlation.engine import CorrelationEngine
from app.db.session import AsyncSessionLocal
from app.models.device import Device, DeviceStatus

logger = logging.getLogger(__name__)

Check = Callable[[Device], Awaitable[list[MetricRecord]]]


def aggregate_status(statuses: list[DeviceStatus]) -> Optional[DeviceStatus]:
    """Todos los chequeos caídos = DOWN; cualquier falla parcial = DEGRADED."""
    if not statuses:
        return None
    if all(s == DeviceStatus.DOWN for s in statuses):
        return DeviceStatus.DOWN
    if any(s in (DeviceStatus.DOWN, DeviceStatus.DEGRADED) for s in statuses):
        return DeviceStatus.DEGRADED
    return DeviceStatus.UP


class CollectorEngine:
    def __init__(
        self,
        buffer: Optional[MetricBuffer] = None,
        check_fns: Optional[list[Check]] = None,
        interval: Optional[float] = None,
        syslog_port: Optional[int] = None,
        correlator: Optional[CorrelationEngine] = None,
        dispatcher: Optional[AlertDispatcher] = None,
        refresh_interval: Optional[float] = None,
    ):
        self.buffer = buffer or MetricBuffer(settings.BATCH_SIZE, settings.FLUSH_INTERVAL)
        self.correlator = correlator or CorrelationEngine(settings.FLAP_THRESHOLD, settings.FLAP_WINDOW)
        self.dispatcher = dispatcher or AlertDispatcher()
        self._checks = check_fns or [checks.check_icmp, checks.check_rtsp, checks.check_snmp]
        self._interval = interval if interval is not None else settings.POLL_INTERVAL
        self._refresh_interval = (
            refresh_interval if refresh_interval is not None else settings.DEVICE_REFRESH_INTERVAL
        )
        self._syslog_port = settings.SYSLOG_PORT if syslog_port is None else syslog_port
        self._sem = asyncio.Semaphore(settings.MAX_CONCURRENT_CHECKS)
        self._device_tasks: dict[str, tuple[datetime, asyncio.Task]] = {}
        self._refresh_task: Optional[asyncio.Task] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self.ip_to_device: dict[str, str] = {}

    async def _load_devices(self) -> list[Device]:
        async with AsyncSessionLocal() as session:
            return list((await session.execute(select(Device))).scalars())

    async def poll_device(self, device: Device) -> None:
        async with self._sem:
            records: list[MetricRecord] = []
            for check in self._checks:
                try:
                    records.extend(await check(device))
                except Exception:
                    logger.exception("Fallo en %s para %s", check.__name__, device.hostname)

        statuses = [r.status for r in records if r.status is not None]
        for r in records:
            r.status = None  # el estado del dispositivo es el agregado, no el de cada chequeo
            self.buffer.put(r)
        status = aggregate_status(statuses)
        if status is None:
            return
        self.buffer.put(MetricRecord(device.id, "DEVICE_STATUS", status=status))
        self.dispatcher.dispatch(self.correlator.process(device.id, status))

    async def _device_loop(self, device: Device) -> None:
        while True:
            await self.poll_device(device)
            await asyncio.sleep(self._interval)

    async def sync_devices(self) -> None:
        """Alinea los ciclos de sondeo con el inventario actual."""
        devices = await self._load_devices()
        self.correlator.set_topology(devices)
        self.ip_to_device.clear()
        self.ip_to_device.update({d.ip_address: d.id for d in devices})
        current = {d.id: d for d in devices}

        for device_id, (updated, task) in list(self._device_tasks.items()):
            dev = current.get(device_id)
            if dev is None or dev.updated_at != updated:
                task.cancel()
                del self._device_tasks[device_id]
        for device_id, dev in current.items():
            if device_id not in self._device_tasks:
                self._device_tasks[device_id] = (
                    dev.updated_at, asyncio.create_task(self._device_loop(dev))
                )

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval)
            try:
                await self.sync_devices()
                self.dispatcher.dispatch(self.correlator.tick())
            except Exception:
                logger.exception("Error al refrescar inventario")

    async def start(self) -> None:
        await self.buffer.start()
        if self._syslog_port:
            self._transport = await start_syslog_server(
                self.buffer, self.ip_to_device, settings.SYSLOG_HOST, self._syslog_port
            )
        await self.sync_devices()
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    @property
    def syslog_port(self) -> Optional[int]:
        if self._transport:
            return self._transport.get_extra_info("sockname")[1]
        return None

    async def stop(self) -> None:
        tasks = [t for _, t in self._device_tasks.values()]
        if self._refresh_task:
            tasks.append(self._refresh_task)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._device_tasks.clear()
        self._refresh_task = None
        if self._transport:
            self._transport.close()
        await self.dispatcher.drain()
        await self.buffer.stop()
