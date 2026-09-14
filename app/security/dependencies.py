from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.security.authentication import (
    AuthenticationError,
    decode_access_token,
)
from app.security.principals import Principal


# ============================================================
# HTTP Bearer Authentication
# ============================================================

bearer_scheme = HTTPBearer(auto_error=False)


# ============================================================
# Current Authenticated Principal
# ============================================================


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
) -> Principal:
    """
    Extract and validate the JWT Bearer token.

    Returns:
        Principal representing the authenticated user.

    Raises:
        HTTP 401 when authentication is missing,
        malformed, invalid, or expired.
    """

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return decode_access_token(
            credentials.credentials
        )

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    