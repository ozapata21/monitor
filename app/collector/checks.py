import asyncio
import json
import time
from urllib.parse import urlparse

from icmplib import async_ping

from app.collector.buffer import MetricRecord
from app.core.security import decrypt_credential
from app.models.device import Device, DeviceStatus


async def check_icmp(device: Device, timeout: float = 2.0, count: int = 3) -> list[MetricRecord]:
    try:
        host = await async_ping(
            device.ip_address, count=count, interval=0.2, timeout=timeout, privileged=False
        )
    except Exception as exc:
        return [MetricRecord(device.id, "ICMP_RTT", None, DeviceStatus.DOWN, f"error: {exc}")]

    if not host.is_alive:
        status = DeviceStatus.DOWN
    elif host.packet_loss > 0:
        status = DeviceStatus.DEGRADED
    else:
        status = DeviceStatus.UP
    return [
        MetricRecord(device.id, "ICMP_RTT", host.avg_rtt if host.is_alive else None, status),
        MetricRecord(device.id, "ICMP_LOSS", host.packet_loss * 100),
    ]


async def check_rtsp(device: Device, timeout: float = 3.0) -> list[MetricRecord]:
    """Handshake RTSP OPTIONS sobre TCP; no registra credenciales."""
    if not device.rtsp_url_encrypted:
        return []
    url = urlparse(decrypt_credential(device.rtsp_url_encrypted))
    host, port = url.hostname or device.ip_address, url.port or 554
    start = time.perf_counter()
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        request = f"OPTIONS rtsp://{host}:{port}{url.path or '/'} RTSP/1.0\r\nCSeq: 1\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
        elapsed = (time.perf_counter() - start) * 1000
        if line.startswith(b"RTSP/"):
            return [MetricRecord(device.id, "RTSP", elapsed, DeviceStatus.UP)]
        return [MetricRecord(device.id, "RTSP", elapsed, DeviceStatus.DEGRADED, "respuesta no RTSP")]
    except (OSError, asyncio.TimeoutError) as exc:
        return [MetricRecord(device.id, "RTSP", None, DeviceStatus.DOWN, type(exc).__name__)]
    finally:
        if writer:
            writer.close()


async def check_snmp(device: Device, timeout: float = 3.0) -> list[MetricRecord]:
    """Consulta sysUpTime vía SNMPv3. Credenciales: JSON cifrado en snmp_v3_encrypted."""
    if not device.snmp_v3_encrypted:
        return []
    from pysnmp.hlapi.asyncio import (
        ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget,
        UsmUserData, getCmd, usmHMACSHAAuthProtocol, usmAesCfb128Protocol,
    )

    creds = json.loads(decrypt_credential(device.snmp_v3_encrypted))
    engine = SnmpEngine()
    try:
        target = await UdpTransportTarget.create((device.ip_address, 161), timeout=timeout, retries=1) \
            if hasattr(UdpTransportTarget, "create") else UdpTransportTarget(
                (device.ip_address, 161), timeout=timeout, retries=1)
        err_ind, err_status, _, var_binds = await getCmd(
            engine,
            UsmUserData(
                creds["user"], creds["auth_key"], creds["priv_key"],
                authProtocol=usmHMACSHAAuthProtocol, privProtocol=usmAesCfb128Protocol,
            ),
            target,
            ContextData(),
            ObjectType(ObjectIdentity("1.3.6.1.2.1.1.3.0")),
        )
    except Exception as exc:
        return [MetricRecord(device.id, "SNMP_UPTIME", None, DeviceStatus.DOWN, type(exc).__name__)]
    finally:
        engine.closeDispatcher()

    if err_ind or err_status:
        return [MetricRecord(device.id, "SNMP_UPTIME", None, DeviceStatus.DOWN, str(err_ind or err_status))]
    return [MetricRecord(device.id, "SNMP_UPTIME", float(var_binds[0][1]) / 100, DeviceStatus.UP)]
