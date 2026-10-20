from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "NOC Python Monitor"
    VERSION: str = "1.0.0"

    # Clave Fernet (32 bytes en base64 urlsafe). Solo para desarrollo: definir en .env en producción.
    APP_SECRET_KEY: str = "6daGLZl9IAN8zVW_31wNbhWG7WKV5nVGbRR9_RwZV5Y="

    DATABASE_URL: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "monitor"
    DB_USER: str = "monitorti"
    DB_PASSWORD: str = "andro470"

    # Solo desarrollo: definir JWT_SECRET_KEY y credenciales admin en .env en producción.
    JWT_SECRET_KEY: str = "dev-only-change-me-jwt-secret-key-0123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = "ChangeMe123!"

    POLL_INTERVAL: float = 30.0
    DEVICE_REFRESH_INTERVAL: float = 60.0
    FLAP_THRESHOLD: int = 4
    FLAP_WINDOW: float = 300.0
    WEBHOOK_URL: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    ALERT_EMAIL_TO: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT: float = 10.0
    EMAIL_LOG_FILE: str = "logs/email_notifications.log"
    EMAIL_LOG_MAX_BYTES: int = 5_000_000
    EMAIL_LOG_BACKUP_COUNT: int = 3
    MAX_CONCURRENT_CHECKS: int = 50
    BATCH_SIZE: int = 100
    FLUSH_INTERVAL: float = 5.0
    SYSLOG_HOST: str = "0.0.0.0"
    SYSLOG_PORT: int = 5514  # 0 desactiva el receptor


settings = Settings()
