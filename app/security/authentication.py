from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

import jwt

from app.core.config import settings


class AuthenticationError(Exception):
    """Raised when a bearer token is invalid or not linked to an account."""


class AuthenticationConfigurationError(RuntimeError):
    """Raised when OIDC verification is not configured safely."""


class AuthenticationProviderUnavailable(RuntimeError):
    """Raised when the OIDC signing keys cannot be reached."""


@dataclass(frozen=True)
class OIDCIdentity:
    issuer: str
    subject: str


_ASYMMETRIC_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
    }
)


def _oidc_settings() -> tuple[str, str, str, list[str]]:
    issuer = settings.OIDC_ISSUER_URL.strip()
    audience = settings.OIDC_AUDIENCE.strip()
    jwks_url = settings.OIDC_JWKS_URL.strip()
    algorithms = [
        value.strip()
        for value in settings.OIDC_SIGNING_ALGORITHMS.split(",")
        if value.strip()
    ]

    if not issuer or not audience or not jwks_url:
        raise AuthenticationConfigurationError(
            "OIDC issuer, audience, and JWKS URL must be configured."
        )
    if not algorithms or any(value not in _ASYMMETRIC_ALGORITHMS for value in algorithms):
        raise AuthenticationConfigurationError(
            "OIDC signing algorithms must be an explicit asymmetric algorithm list."
        )

    issuer_parts = urlparse(issuer)
    jwks_parts = urlparse(jwks_url)
    if issuer_parts.scheme != "https" or not issuer_parts.netloc:
        raise AuthenticationConfigurationError("OIDC issuer must use HTTPS.")
    if jwks_parts.scheme != "https" or not jwks_parts.netloc:
        raise AuthenticationConfigurationError("OIDC JWKS URL must use HTTPS.")

    return issuer, audience, jwks_url, algorithms


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str, timeout: int) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        jwks_url,
        cache_keys=True,
        timeout=timeout,
    )


async def verify_oidc_access_token(token: str) -> OIDCIdentity:
    """Verify an OIDC JWT access token and return only its issuer and subject.

    Role and domain scope claims are deliberately ignored. They are resolved
    from KodiLedger's active user and membership records after verification.
    """
    issuer, audience, jwks_url, algorithms = _oidc_settings()
    client = _jwks_client(jwks_url, settings.OIDC_JWKS_TIMEOUT_SECONDS)

    try:
        signing_key = await asyncio.to_thread(
            client.get_signing_key_from_jwt,
            token,
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise AuthenticationProviderUnavailable(
            "OIDC signing keys are temporarily unavailable."
        ) from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid bearer token.") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=algorithms,
            issuer=issuer,
            audience=audience,
            options={
                "require": ["iss", "sub", "aud", "exp", "iat"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired bearer token.") from exc

    subject = claims.get("sub")
    claim_issuer = claims.get("iss")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationError("Bearer token subject is invalid.")
    if not isinstance(claim_issuer, str) or claim_issuer != issuer:
        raise AuthenticationError("Bearer token issuer is invalid.")

    return OIDCIdentity(issuer=claim_issuer, subject=subject)
