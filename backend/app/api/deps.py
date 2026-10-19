"""Request dependencies: authentication and role-based authorization."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import ApiError
from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    role: str          # STUDENT | FACULTY | ADMIN
    name: str

    @property
    def is_student(self) -> bool:
        return self.role == "STUDENT"

    @property
    def is_staff(self) -> bool:
        return self.role in ("FACULTY", "ADMIN")

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "Your session has expired. Please sign in again.") from None
    except jwt.PyJWTError:
        raise ApiError(401, "unauthorized", "Invalid authentication token.") from None
    return CurrentUser(id=int(payload["sub"]), role=payload["role"], name=payload.get("name", ""))


def require_roles(*roles: str):
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise ApiError(403, "forbidden", f"This action requires role: {' or '.join(roles)}.")
        return user

    return checker


require_staff = require_roles("FACULTY", "ADMIN")
require_admin = require_roles("ADMIN")
require_student = require_roles("STUDENT")
