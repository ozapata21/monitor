import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def record_audit(
    session: AsyncSession,
    request: Request,
    user_id: str,
    action: str,
    resource_id: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Agrega el registro a la sesión; se confirma junto con la operación auditada."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_id=resource_id,
            ip_address=client_ip(request),
            details_json=json.dumps(details) if details else None,
        )
    )
