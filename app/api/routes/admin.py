from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import record_audit
from app.api.deps import get_db, require_admin
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.user import AuditLogRead, UserCreate, UserRead

router = APIRouter(tags=["admin"])


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    exists = (await db.execute(select(User.id).where(User.username == payload.username))).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "El usuario ya existe")
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.flush()
    record_audit(db, request, admin.id, "CREATE_USER", user.id, {"role": user.role.value})
    await db.commit()
    return user


@router.get("/audit-logs", response_model=list[AuditLogRead])
async def list_audit_logs(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(min(limit, 500)).offset(offset)
    return (await db.execute(q)).scalars().all()
