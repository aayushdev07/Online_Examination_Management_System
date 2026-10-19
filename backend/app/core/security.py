"""Password hashing (bcrypt) and JWT access tokens."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"
ROLES = ("STUDENT", "FACULTY", "ADMIN")


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; schemas cap passwords at 72 characters
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # malformed hash in the database
        return False


def create_access_token(user_id: int, role: str, name: str) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "name": name,
               "iat": now, "exp": now + timedelta(seconds=expires_in)}
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError when the token is invalid or expired."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=[ALGORITHM],
                         options={"require": ["sub", "role", "exp"]})
    if payload.get("role") not in ROLES:
        raise jwt.InvalidTokenError("unknown role")
    return payload
