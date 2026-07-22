import base64
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_fernet = Fernet(base64.urlsafe_b64encode(settings.TOKEN_ENCRYPTION_KEY.encode()[:32]))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def encrypt_token(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    return _fernet.decrypt(encrypted.encode()).decode()


def make_unsubscribe_token(user_id: str) -> str:
    """HMAC-signed token for one-click email unsubscribe (no expiry)."""
    import hashlib, hmac, base64
    sig = hmac.new(settings.SECRET_KEY.encode(), user_id.encode(), hashlib.sha256).digest()
    payload = f"{user_id}:{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def verify_unsubscribe_token(token: str) -> str | None:
    """Verify token and return user_id, or None if invalid."""
    import hashlib, hmac, base64
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = base64.urlsafe_b64decode(padded).decode()
        user_id, sig_b64 = payload.rsplit(":", 1)
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        expected = hmac.new(settings.SECRET_KEY.encode(), user_id.encode(), hashlib.sha256).digest()
        if hmac.compare_digest(sig, expected):
            return user_id
    except Exception:
        pass
    return None
