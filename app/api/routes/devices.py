import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import record_audit
from app.api.deps import get_db, require_admin, require_operator, require_viewer
from app.core.security import encrypt_credential
from app.models.device import Device, DeviceStatus, DeviceType
from app.models.metric import Metric
from app.models.user import User
from app.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate
from app.schemas.metric import MetricRead

router = APIRouter(prefix="/devices", tags=["devices"])


async def _get_or_404(db: AsyncSession, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispositivo no encontrado")
    return device


async def _check_parent(db: AsyncSession, device_id: Optional[str], parent_id: Optional[str]) -> None:
    """Valida que el padre exista y que no se forme un ciclo."""
    if parent_id is None:
        return
    if parent_id == device_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Un dispositivo no puede ser su propio padre")
    current = await db.get(Device, parent_id)
    if current is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dispositivo padre inexistente")
    while current is not None and device_id is not None:
        if current.parent_device_id == device_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La jerarquía formaría un ciclo")
        current = await db.get(Device, current.parent_device_id) if current.parent_device_id else None


def _apply_credentials(device: Device, data: dict) -> None:
    if data.get("snmp_community") is not None:
        device.snmp_community_encrypted = encrypt_credential(data["snmp_community"])
    if data.get("rtsp_url") is not None:
        device.rtsp_url_encrypted = encrypt_credential(data["rtsp_url"])
    if data.get("snmp_v3") is not None:
        device.snmp_v3_encrypted = encrypt_credential(json.dumps(data["snmp_v3"]))


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    site_id: Optional[str] = None,
    device_type: Optional[DeviceType] = None,
    status_: Optional[DeviceStatus] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
):
    q = select(Device).order_by(Device.hostname).limit(min(limit, 500)).offset(offset)
    if site_id:
        q = q.where(Device.site_id == site_id)
    if device_type:
        q = q.where(Device.device_type == device_type)
    if status_:
        q = q.where(Device.status == status_)
    return (await db.execute(q)).scalars().all()


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_viewer)
):
    return await _get_or_404(db, device_id)


@router.get("/{device_id}/metrics", response_model=list[MetricRead])
async def device_metrics(
    device_id: str,
    metric_type: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
):
    await _get_or_404(db, device_id)
    q = select(Metric).where(Metric.device_id == device_id).order_by(Metric.timestamp.desc()).limit(min(limit, 2000))
    if metric_type:
        q = q.where(Metric.metric_type == metric_type)
    return (await db.execute(q)).scalars().all()


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    await _check_parent(db, None, payload.parent_device_id)
    data = payload.model_dump()
    device = Device(**{k: data[k] for k in DeviceRead.model_fields if k in data})
    _apply_credentials(device, data)
    db.add(device)
    await db.flush()
    record_audit(db, request, user.id, "REGISTER_DEVICE", device.id,
                 {"hostname": device.hostname, "ip_address": device.ip_address})
    await db.commit()
    await db.refresh(device)
    return device


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: str,
    payload: DeviceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
):
    device = await _get_or_404(db, device_id)
    data = payload.model_dump(exclude_unset=True)
    if "parent_device_id" in data:
        await _check_parent(db, device_id, data["parent_device_id"])
    for field in DeviceRead.model_fields:
        if field in data and field not in ("id", "status", "created_at", "updated_at"):
            setattr(device, field, data[field])
    _apply_credentials(device, data)
    record_audit(db, request, user.id, "UPDATE_DEVICE", device.id, {"fields": sorted(data)})
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    device = await _get_or_404(db, device_id)
    has_children = (await db.execute(
        select(Device.id).where(Device.parent_device_id == device_id).limit(1)
    )).first()
    if has_children:
        raise HTTPException(status.HTTP_409_CONFLICT, "El dispositivo tiene dependientes")
    record_audit(db, request, user.id, "DELETE_DEVICE", device.id, {"hostname": device.hostname})
    await db.delete(device)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
