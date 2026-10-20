from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import record_audit
from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import Token, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

# Hash ficticio para igualar el tiempo de respuesta cuando el usuario no existe
_DUMMY_HASH = hash_password("dummy-password")


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.username == form.username))).scalar_one_or_none()
    valid = verify_password(form.password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not valid or not user.is_active:
        record_audit(db, request, form.username[:50], "LOGIN_FAILED", form.username[:50])
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")
    record_audit(db, request, user.id, "LOGIN", user.id)
    await db.commit()
    return Token(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)):
    return user
