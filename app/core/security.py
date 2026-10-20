from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_cipher_suite = Fernet(settings.APP_SECRET_KEY.encode())
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def encrypt_credential(raw_credential: str) -> str:
    """Cifra un secreto (comunidad SNMP, URL RTSP) para almacenamiento seguro."""
    if not raw_credential:
        return ""
    return _cipher_suite.encrypt(raw_credential.encode()).decode()


def decrypt_credential(encrypted_credential: str) -> str:
    """Descifra una credencial almacenada en base de datos."""
    if not encrypted_credential:
        return ""
    return _cipher_suite.decrypt(encrypted_credential.encode()).decode()


def hash_password(password: str) -> str:
    """Genera hash bcrypt para passwords de usuarios de la API."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica el password plano contra el hash almacenado."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": subject, "role": role, "exp": expire},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
