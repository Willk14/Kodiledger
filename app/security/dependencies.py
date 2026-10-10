from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.security.authentication import (
    AuthenticationConfigurationError,
    AuthenticationError,
    AuthenticationProviderUnavailable,
    verify_oidc_access_token,
)
from app.security.identity import (
    IdentityAuthorizationError,
    resolve_authenticated_context,
)
from app.security.principals import Principal


# ============================================================
# HTTP Bearer Authentication
# ============================================================

bearer_scheme = HTTPBearer(auto_error=False)


# ============================================================
# Current Authenticated Principal
# ============================================================


async def get_authenticated_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """
    Verify an OIDC access token and resolve its identity through KodiLedger
    account and membership records.

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
        identity = await verify_oidc_access_token(credentials.credentials)
        return await resolve_authenticated_context(db, identity)

    except (
        AuthenticationConfigurationError,
        AuthenticationProviderUnavailable,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from exc

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except IdentityAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from exc


# Existing authorization modules use this established dependency name.
get_current_principal = get_authenticated_context
