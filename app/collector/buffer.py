import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update

from app.db.session import AsyncSessionLocal
from app.models.device import Device, DeviceStatus
from app.models.metric import Metric

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class MetricRecord:
    device_id: str
    metric_type: str
    value: Optional[float] = None
    status: Optional[DeviceStatus] = None  # si se define, actualiza Device.status
    detail: Optional[str] = None
    timestamp: datetime = field(default_factory=_utcnow)


class MetricBuffer:
    """Cola en memoria que persiste las métricas en lotes."""

    def __init__(self, batch_size: int = 100, flush_interval: float = 5.0, maxsize: int = 10000):
        self._queue: asyncio.Queue[MetricRecord] = asyncio.Queue(maxsize=maxsize)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._task: Optional[asyncio.Task] = None

    def put(self, record: MetricRecord) -> None:
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning("Buffer lleno, métrica descartada: %s", record.metric_type)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.flush()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("Error al persistir lote de métricas")

    async def flush(self) -> int:
        batch: list[MetricRecord] = []
        while len(batch) < self._batch_size and not self._queue.empty():
            batch.append(self._queue.get_nowait())
        if not batch:
            return 0

        # Último estado conocido por dispositivo dentro del lote
        statuses = {r.device_id: r.status for r in batch if r.status is not None}
        try:
            async with AsyncSessionLocal() as session:
                session.add_all(
                    Metric(
                        device_id=r.device_id,
                        timestamp=r.timestamp,
                        metric_type=r.metric_type,
                        value=r.value,
                        status=r.status.value if r.status else None,
                        detail=r.detail,
                    )
                    for r in batch
                )
                for device_id, status in statuses.items():
                    await session.execute(
                        update(Device).where(Device.id == device_id).values(status=status)
                    )
                await session.commit()
        except Exception:
            for r in batch:
                self.put(r)
            raise
        if not self._queue.empty():
            return len(batch) + await self.flush()
        return len(batch)
