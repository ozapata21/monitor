import pytest
from sqlalchemy import text

from app.core.security import (
    decrypt_credential,
    encrypt_credential,
    hash_password,
    verify_password,
)
from app.db.session import AsyncSessionLocal, init_db
from app.models.device import Device, DeviceType


def test_encryption():
    raw_secret = "rtsp://admin:SecretPassword123@192.168.1.50:554/stream1"
    encrypted = encrypt_credential(raw_secret)
    assert encrypted != raw_secret
    assert decrypt_credential(encrypted) == raw_secret


def test_password_hash():
    hashed = hash_password("s3cret")
    assert verify_password("s3cret", hashed)
    assert not verify_password("otro", hashed)


@pytest.mark.asyncio
async def test_database_and_wal():
    await init_db()
    async with AsyncSessionLocal() as session:
        mode = (await session.execute(text("PRAGMA journal_mode"))).scalar()
        assert mode == "wal"

        parent_sw = Device(
            hostname="SW-CORE-01",
            ip_address="10.0.0.1",
            device_type=DeviceType.SWITCH,
            site_id="SITE-CENTRAL",
            snmp_community_encrypted=encrypt_credential("public_snmp_key"),
        )
        session.add(parent_sw)
        await session.commit()
        await session.refresh(parent_sw)

        cam = Device(
            hostname="CAM-ENTRADA",
            ip_address="10.0.0.15",
            device_type=DeviceType.CAMERA,
            site_id="SITE-CENTRAL",
            parent_device_id=parent_sw.id,
            rtsp_url_encrypted=encrypt_credential("rtsp://cam_user:pass@10.0.0.15:554/live"),
        )
        session.add(cam)
        await session.commit()

        assert cam.parent_device_id == parent_sw.id
        assert decrypt_credential(cam.rtsp_url_encrypted).startswith("rtsp://")
