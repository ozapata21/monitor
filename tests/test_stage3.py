import httpx
import pytest
from sqlalchemy import select

from app.core.security import decrypt_credential
from app.db.session import AsyncSessionLocal, init_db
from app.models.audit import AuditLog
from app.models.device import Device
from main import app, bootstrap_admin


@pytest.fixture
async def client():
    await init_db()
    await bootstrap_admin()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _token(c, username, password):
    r = await c.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _user_headers(c, admin_h, name, role):
    r = await c.post("/users", json={"username": name, "password": "Passw0rd!x", "role": role}, headers=admin_h)
    assert r.status_code in (201, 409)
    return await _token(c, name, "Passw0rd!x")


async def test_login_failure_and_no_token(client):
    r = await client.post("/auth/login", data={"username": "admin", "password": "mala"})
    assert r.status_code == 401
    assert (await client.get("/devices")).status_code == 401


async def test_rbac_and_audit(client):
    admin = await _token(client, "admin", "ChangeMe123!")
    operator = await _user_headers(client, admin, "op1", "OPERATOR")
    viewer = await _user_headers(client, admin, "view1", "VIEWER")

    body = {"hostname": "SW1", "ip_address": "10.1.1.1", "device_type": "SWITCH", "site_id": "S1",
            "snmp_community": "secreto"}
    assert (await client.post("/devices", json=body, headers=viewer)).status_code == 403
    r = await client.post("/devices", json=body, headers=operator)
    assert r.status_code == 201
    parent = r.json()
    assert parent["email_notifications_enabled"] is True
    assert "snmp_community" not in parent and "snmp_community_encrypted" not in parent

    muted = await client.patch(
        f"/devices/{parent['id']}",
        json={"email_notifications_enabled": False},
        headers=operator,
    )
    assert muted.status_code == 200
    assert muted.json()["email_notifications_enabled"] is False
    null_preference = await client.patch(
        f"/devices/{parent['id']}",
        json={"email_notifications_enabled": None},
        headers=operator,
    )
    assert null_preference.status_code == 422

    async with AsyncSessionLocal() as s:
        dev = await s.get(Device, parent["id"])
        assert dev.snmp_community_encrypted != "secreto"
        assert decrypt_credential(dev.snmp_community_encrypted) == "secreto"

    child = {"hostname": "CAM1", "ip_address": "10.1.1.2", "device_type": "CAMERA", "site_id": "S1",
             "parent_device_id": parent["id"]}
    cr = await client.post("/devices", json=child, headers=operator)
    assert cr.status_code == 201

    assert (await client.get("/devices", headers=viewer)).status_code == 200
    bad_ip = await client.post("/devices", json={**child, "ip_address": "x"}, headers=operator)
    assert bad_ip.status_code == 422
    # ciclo: el padre no puede colgar de su hijo
    cyc = await client.patch(f"/devices/{parent['id']}", json={"parent_device_id": cr.json()["id"]}, headers=operator)
    assert cyc.status_code == 422

    assert (await client.delete(f"/devices/{parent['id']}", headers=operator)).status_code == 403
    assert (await client.delete(f"/devices/{parent['id']}", headers=admin)).status_code == 409
    assert (await client.delete(f"/devices/{cr.json()['id']}", headers=admin)).status_code == 204

    assert (await client.get("/audit-logs", headers=operator)).status_code == 403
    logs = (await client.get("/audit-logs", headers=admin)).json()
    actions = {entry["action"] for entry in logs}
    assert {"REGISTER_DEVICE", "DELETE_DEVICE", "CREATE_USER", "LOGIN"} <= actions
    assert not any("secreto" in (entry["details_json"] or "") for entry in logs)

    async with AsyncSessionLocal() as s:
        n = len((await s.execute(select(AuditLog).where(AuditLog.action == "REGISTER_DEVICE"))).scalars().all())
        assert n >= 2
