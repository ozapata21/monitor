from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, settings



def database_url_from_settings(config: Settings) -> str | URL:
    if config.DATABASE_URL:
        return config.DATABASE_URL
    if config.DB_HOST:
        if not config.DB_USER or not config.DB_PASSWORD or not config.DB_NAME:
            raise ValueError("DB_USER, DB_PASSWORD y DB_NAME son requeridos cuando se configura DB_HOST")
        return URL.create(
            "mysql+aiomysql",
            username=config.DB_USER,
            password=config.DB_PASSWORD,
            host=config.DB_HOST,
            port=config.DB_PORT,
            database=config.DB_NAME,
        )
    return "sqlite+aiosqlite:///./noc_monitor.db"


engine = create_async_engine(database_url_from_settings(settings), echo=False)

if engine.url.get_backend_name() == "sqlite":
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Crea las tablas si no existen."""
    import app.models  # noqa: F401  registra los modelos en Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
