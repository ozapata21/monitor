from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.api.routes import admin, alerts, auth, devices
from app.collector.engine import CollectorEngine
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.models.user import Role, User


async def bootstrap_admin() -> None:
    """Crea el primer administrador si no existe ningún usuario."""
    async with AsyncSessionLocal() as session:
        if (await session.execute(select(User.id).limit(1))).first():
            return
        session.add(User(
            username=settings.FIRST_ADMIN_USERNAME,
            hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
            role=Role.ADMIN,
        ))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await bootstrap_admin()
    engine = CollectorEngine()
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(admin.router)
app.include_router(alerts.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
