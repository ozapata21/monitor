import asyncio
import re

from app.collector.buffer import MetricBuffer, MetricRecord

_PRI = re.compile(rb"^<(\d{1,3})>")


class SyslogProtocol(asyncio.DatagramProtocol):
    def __init__(self, buffer: MetricBuffer, ip_to_device: dict[str, str]):
        self._buffer = buffer
        self._ip_to_device = ip_to_device  # referencia viva, la actualiza el engine

    def datagram_received(self, data: bytes, addr) -> None:
        device_id = self._ip_to_device.get(addr[0])
        if device_id is None:
            return  # origen desconocido
        match = _PRI.match(data)
        severity = int(match.group(1)) % 8 if match else None
        message = data[match.end():] if match else data
        self._buffer.put(
            MetricRecord(
                device_id,
                "SYSLOG",
                float(severity) if severity is not None else None,
                detail=message.decode(errors="replace").strip()[:1000],
            )
        )


async def start_syslog_server(
    buffer: MetricBuffer, ip_to_device: dict[str, str], host: str, port: int
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: SyslogProtocol(buffer, ip_to_device), local_addr=(host, port)
    )
    return transport
