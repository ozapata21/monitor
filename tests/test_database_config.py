import app.models
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.schema import CreateTable

from app.core.config import Settings
from app.db.session import Base, database_url_from_settings


def test_mysql_url_uses_aiomysql_and_escapes_password(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Settings(
        _env_file=None,
        DB_HOST="db.example.com",
        DB_PORT=3307,
        DB_NAME="monitor",
        DB_USER="monitor_user",
        DB_PASSWORD="p@ss:/word",
    )

    url = database_url_from_settings(config)

    assert url.drivername == "mysql+aiomysql"
    assert url.host == "db.example.com"
    assert url.port == 3307
    assert url.database == "monitor"
    assert url.username == "monitor_user"
    assert url.password == "p@ss:/word"


def test_existing_database_url_takes_precedence():
    config = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        DB_HOST="db.example.com",
    )

    assert database_url_from_settings(config) == "sqlite+aiosqlite:///./test.db"


def test_models_compile_for_mysql():
    for table in Base.metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=mysql_dialect()))