import ipaddress
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.device import DeviceStatus, DeviceType


class SnmpV3Credentials(BaseModel):
    user: str = Field(min_length=1)
    auth_key: str = Field(min_length=8)
    priv_key: str = Field(min_length=8)


class DeviceBase(BaseModel):
    hostname: str = Field(min_length=1, max_length=100)
    ip_address: str = Field(min_length=3, max_length=45)
    device_type: DeviceType
    site_id: str = Field(min_length=1, max_length=50)
    parent_device_id: Optional[str] = None
    email_notifications_enabled: bool = True

    @field_validator("ip_address")
    @classmethod
    def _valid_ip(cls, v: str) -> str:
        ipaddress.ip_address(v)
        return v


class DeviceCreate(DeviceBase):
    # Credenciales en claro solo en la entrada; se cifran antes de persistir.
    snmp_community: Optional[str] = None
    rtsp_url: Optional[str] = None
    snmp_v3: Optional[SnmpV3Credentials] = None


class DeviceUpdate(BaseModel):
    hostname: Optional[str] = Field(default=None, min_length=1, max_length=100)
    ip_address: Optional[str] = Field(default=None, min_length=3, max_length=45)
    device_type: Optional[DeviceType] = None
    site_id: Optional[str] = Field(default=None, min_length=1, max_length=50)
    parent_device_id: Optional[str] = None
    email_notifications_enabled: Optional[bool] = None
    snmp_community: Optional[str] = None
    rtsp_url: Optional[str] = None
    snmp_v3: Optional[SnmpV3Credentials] = None

    @field_validator("email_notifications_enabled")
    @classmethod
    def _email_notifications_must_be_boolean(cls, value: Optional[bool]) -> Optional[bool]:
        if value is None:
            raise ValueError("email_notifications_enabled no puede ser null")
        return value

    @field_validator("ip_address")
    @classmethod
    def _valid_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            ipaddress.ip_address(v)
        return v


class DeviceRead(DeviceBase):
    """Nunca expone credenciales."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: DeviceStatus
    created_at: datetime
    updated_at: datetime
