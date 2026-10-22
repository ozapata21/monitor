import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DeviceType(str, enum.Enum):
    CAMERA = "CAMERA"
    SWITCH = "SWITCH"
    ROUTER = "ROUTER"
    LINK = "LINK"


class DeviceStatus(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hostname: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    device_type: Mapped[DeviceType] = mapped_column(SQLEnum(DeviceType), nullable=False)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[DeviceStatus] = mapped_column(SQLEnum(DeviceStatus), default=DeviceStatus.UNKNOWN)
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Árbol de dependencias para la correlación de fallos
    parent_device_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("devices.id"), nullable=True
    )

    snmp_community_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rtsp_url_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON cifrado: {"user": ..., "auth_key": ..., "priv_key": ...}
    snmp_v3_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    parent: Mapped[Optional["Device"]] = relationship(
        "Device", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["Device"]] = relationship("Device", back_populates="parent")
