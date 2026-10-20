import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Optional

from app.models.device import Device, DeviceStatus


class AlertKind(str, Enum):
    DOWN = "DOWN"
    RECOVERY = "RECOVERY"
    FLAPPING = "FLAPPING"
    FLAPPING_RESOLVED = "FLAPPING_RESOLVED"


@dataclass
class AlertEvent:
    device_id: str
    hostname: str
    kind: AlertKind
    message: str
    root_cause_id: Optional[str] = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class CorrelationEngine:
    """Correlación en memoria: supresión por dependencia y detección de flapping."""

    def __init__(self, flap_threshold: int = 4, flap_window: float = 300.0):
        self._threshold = flap_threshold
        self._window = flap_window
        self._parents: dict[str, Optional[str]] = {}
        self._names: dict[str, str] = {}
        self._state: dict[str, DeviceStatus] = {}
        self._transitions: dict[str, deque[float]] = defaultdict(deque)
        self._flapping: set[str] = set()
        self._suppressed: set[str] = set()

    def set_topology(self, devices: Iterable[Device]) -> None:
        devices = list(devices)
        self._parents = {d.id: d.parent_device_id for d in devices}
        self._names = {d.id: d.hostname for d in devices}
        for registry in (self._state, self._transitions):
            for gone in set(registry) - set(self._parents):
                del registry[gone]
        self._flapping &= set(self._parents)
        self._suppressed &= set(self._parents)

    def _root_down_ancestor(self, device_id: str) -> Optional[str]:
        """Ancestro DOWN más alto en la jerarquía (causa raíz)."""
        seen: set[str] = set()
        root = None
        current = self._parents.get(device_id)
        while current and current not in seen:
            seen.add(current)
            if self._state.get(current) == DeviceStatus.DOWN:
                root = current
            current = self._parents.get(current)
        return root

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > self._window:
            q.popleft()

    def _event(self, device_id: str, kind: AlertKind, message: str, root: Optional[str] = None) -> AlertEvent:
        return AlertEvent(device_id, self._names.get(device_id, device_id), kind, message, root)

    def _down_or_suppress(self, device_id: str) -> list[AlertEvent]:
        root = self._root_down_ancestor(device_id)
        if root:
            self._suppressed.add(device_id)
            return []
        return [self._event(device_id, AlertKind.DOWN, f"{self._names.get(device_id, device_id)} está caído")]

    def process(self, device_id: str, status: DeviceStatus, now: Optional[float] = None) -> list[AlertEvent]:
        """Procesa el estado agregado de un dispositivo; devuelve las alertas a emitir."""
        now = time.monotonic() if now is None else now
        prev = self._state.get(device_id, DeviceStatus.UNKNOWN)
        name = self._names.get(device_id, device_id)

        if status == prev:
            # Un hijo suprimido cuyo padre ya se recuperó es una falla propia
            if (status == DeviceStatus.DOWN and device_id in self._suppressed
                    and device_id not in self._flapping
                    and not self._root_down_ancestor(device_id)):
                self._suppressed.discard(device_id)
                return [self._event(device_id, AlertKind.DOWN, f"{name} sigue caído tras recuperarse su dependencia")]
            return []

        self._state[device_id] = status
        if prev != DeviceStatus.UNKNOWN:
            q = self._transitions[device_id]
            q.append(now)
            self._prune(q, now)

        if device_id in self._flapping:
            return []
        if len(self._transitions.get(device_id, ())) >= self._threshold:
            self._flapping.add(device_id)
            self._suppressed.discard(device_id)
            return [self._event(
                device_id, AlertKind.FLAPPING,
                f"{name} oscila ({self._threshold}+ cambios en {int(self._window)}s); alertas individuales suprimidas",
            )]

        if status == DeviceStatus.DOWN:
            return self._down_or_suppress(device_id)
        if prev == DeviceStatus.DOWN:
            if device_id in self._suppressed:
                self._suppressed.discard(device_id)
                return []
            return [self._event(device_id, AlertKind.RECOVERY, f"{name} se recuperó")]
        return []

    def tick(self, now: Optional[float] = None) -> list[AlertEvent]:
        """Cierra el flapping de dispositivos estables durante toda la ventana."""
        now = time.monotonic() if now is None else now
        events: list[AlertEvent] = []
        for device_id in list(self._flapping):
            q = self._transitions[device_id]
            self._prune(q, now)
            if q:
                continue
            self._flapping.discard(device_id)
            state = self._state.get(device_id, DeviceStatus.UNKNOWN)
            name = self._names.get(device_id, device_id)
            events.append(self._event(
                device_id, AlertKind.FLAPPING_RESOLVED, f"{name} se estabilizó en estado {state.value}"
            ))
            if state == DeviceStatus.DOWN:
                events.extend(self._down_or_suppress(device_id))
        return events
