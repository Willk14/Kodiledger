from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.security.principals import Principal
from app.security.roles import Role


class AuthenticationError(Exception):
    """Raised when authentication fails."""


def create_access_token(
    *,
    user_id: str,
    role: str | Role,
) -> str:
    """
    Create a signed JWT access token.
    """
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "role": str(role),
        "iat": now,
        "exp": now
        + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Principal:
    """
    Verify and decode a JWT access token.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError(
            "Invalid or expired access token."
        ) from exc

    user_id = payload.get("sub")
    role_value = payload.get("role")

    if not user_id or not role_value:
        raise AuthenticationError(
            "Access token is missing required claims."
        )

    try:
        role = Role(role_value)
    except ValueError as exc:
        raise AuthenticationError(
            "Access token contains an invalid role."
        ) from exc

    return Principal(
        user_id=str(user_id),
        role=role,
    )