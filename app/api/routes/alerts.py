from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_viewer
from app.models.alert import Alert
from app.models.user import User
from app.schemas.alert import AlertRead

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRead])
async def list_alerts(
    device_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
):
    q = select(Alert).order_by(Alert.timestamp.desc()).limit(min(limit, 500)).offset(offset)
    if device_id:
        q = q.where(Alert.device_id == device_id)
    return (await db.execute(q)).scalars().all()
