from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr
import jwt

from app.core.config import settings
from app.core.database import get_db
from app.main import app
import app.security.authentication as authentication
import app.security.dependencies as dependencies
from app.security.authentication import (
    AuthenticationConfigurationError,
    AuthenticationError,
    AuthenticationProviderUnavailable,
    OIDCIdentity,
    verify_oidc_access_token,
)
from app.security.identity import (
    IdentityAuthorizationError,
    resolve_authenticated_context,
)
from app.security.principals import AuthenticatedContext
from app.security.roles import Role


LANDLORD_A = "11111111-1111-1111-1111-111111111111"
LANDLORD_B = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_ID = "55555555-5555-5555-5555-555555555555"


@dataclass
class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakeSession:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.statement: Any = None

    async def execute(self, statement: Any) -> FakeResult:
        self.statement = statement
        return FakeResult(self.rows)


def _oidc_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "https://issuer.example/")
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", "kodiledger-api")
    monkeypatch.setattr(settings, "OIDC_JWKS_URL", "https://issuer.example/jwks")
    monkeypatch.setattr(settings, "OIDC_SIGNING_ALGORITHMS", "RS256")


def _membership_rows(
    *,
    user_id: str,
    role: str = "LANDLORD",
    landlord_id: str | None = LANDLORD_A,
    tenant_id: str | None = None,
    active: bool = True,
) -> list[tuple[Any, ...]]:
    user = SimpleNamespace(id=UUID(user_id), is_active=True)
    membership = SimpleNamespace(
        role=role,
        landlord_id=UUID(landlord_id) if landlord_id else None,
        tenant_id=UUID(tenant_id) if tenant_id else None,
        is_active=active,
    )
    return [(user, membership)]


@pytest.mark.asyncio
async def test_oidc_verification_returns_only_verified_issuer_and_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _oidc_settings(monkeypatch)
    fake_key = SimpleNamespace(key="test-public-key")

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, token: str) -> Any:
            assert token == "signed-token"
            return fake_key

    monkeypatch.setattr(authentication, "_jwks_client", lambda *_: FakeJwksClient())
    decode_args: dict[str, Any] = {}

    def fake_decode(token: str, key: str, **kwargs: Any) -> dict[str, Any]:
        decode_args.update(kwargs)
        assert token == "signed-token"
        assert key == "test-public-key"
        return {
            "iss": "https://issuer.example/",
            "sub": "external-user-42",
            "aud": "kodiledger-api",
            "exp": 2_000_000_000,
            "iat": 1_900_000_000,
            # Authorization claims from the provider are deliberately ignored.
            "role": "ADMIN",
            "landlord_id": LANDLORD_B,
        }

    monkeypatch.setattr(authentication.jwt, "decode", fake_decode)

    identity = await verify_oidc_access_token("signed-token")

    assert identity == OIDCIdentity(
        issuer="https://issuer.example/",
        subject="external-user-42",
    )
    assert decode_args["algorithms"] == ["RS256"]
    assert decode_args["audience"] == "kodiledger-api"
    assert decode_args["issuer"] == "https://issuer.example/"
    assert decode_args["options"]["verify_signature"] is True


@pytest.mark.asyncio
async def test_invalid_oidc_signature_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _oidc_settings(monkeypatch)

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, token: str) -> Any:
            return SimpleNamespace(key="test-public-key")

    monkeypatch.setattr(authentication, "_jwks_client", lambda *_: FakeJwksClient())
    monkeypatch.setattr(
        authentication.jwt,
        "decode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(jwt.InvalidSignatureError()),
    )

    with pytest.raises(AuthenticationError, match="Invalid or expired"):
        await verify_oidc_access_token("bad-token")


@pytest.mark.asyncio
async def test_oidc_requires_asymmetric_algorithm_and_all_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _oidc_settings(monkeypatch)
    monkeypatch.setattr(settings, "OIDC_SIGNING_ALGORITHMS", "HS256")

    with pytest.raises(AuthenticationConfigurationError, match="asymmetric"):
        await verify_oidc_access_token("token")

    monkeypatch.setattr(settings, "OIDC_SIGNING_ALGORITHMS", "RS256")
    monkeypatch.setattr(settings, "OIDC_JWKS_URL", "")
    with pytest.raises(AuthenticationConfigurationError, match="JWKS URL"):
        await verify_oidc_access_token("token")


@pytest.mark.asyncio
async def test_trusted_membership_resolves_role_and_landlord_scope() -> None:
    user_id = "11111111-2222-3333-4444-555555555555"
    session = FakeSession(_membership_rows(user_id=user_id))

    context = await resolve_authenticated_context(
        session,  # type: ignore[arg-type]
        OIDCIdentity("https://issuer.example/", "external-user-42"),
    )

    assert isinstance(context, AuthenticatedContext)
    assert context.user_id == user_id
    assert context.role is Role.LANDLORD
    assert context.landlord_id == LANDLORD_A
    assert context.tenant_id is None
    assert "identity_issuer" in str(session.statement)
    assert "identity_subject" in str(session.statement)


@pytest.mark.asyncio
async def test_tenant_context_comes_from_tenant_membership() -> None:
    user_id = "11111111-2222-3333-4444-555555555555"
    session = FakeSession(
        _membership_rows(
            user_id=user_id,
            role="TENANT",
            landlord_id=LANDLORD_A,
            tenant_id=TENANT_ID,
        )
    )

    context = await resolve_authenticated_context(
        session,  # type: ignore[arg-type]
        OIDCIdentity("https://issuer.example/", "external-tenant"),
    )

    assert context.role is Role.TENANT
    assert context.landlord_id == LANDLORD_A
    assert context.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_unlinked_identity_and_inactive_membership_are_rejected() -> None:
    identity = OIDCIdentity("https://issuer.example/", "unknown-subject")
    with pytest.raises(AuthenticationError, match="not linked"):
        await resolve_authenticated_context(FakeSession([]), identity)  # type: ignore[arg-type]

    rows = _membership_rows(
        user_id="11111111-2222-3333-4444-555555555555",
        active=False,
    )
    with pytest.raises(IdentityAuthorizationError, match="No active"):
        await resolve_authenticated_context(FakeSession(rows), identity)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_system_membership_and_ambiguous_memberships_fail_closed() -> None:
    identity = OIDCIdentity("https://issuer.example/", "external-user")
    system_rows = _membership_rows(
        user_id="11111111-2222-3333-4444-555555555555",
        role="SYSTEM",
        landlord_id=None,
    )
    with pytest.raises(IdentityAuthorizationError, match="System identity"):
        await resolve_authenticated_context(FakeSession(system_rows), identity)  # type: ignore[arg-type]

    multiple_rows = _membership_rows(
        user_id="11111111-2222-3333-4444-555555555555",
    ) * 2
    with pytest.raises(IdentityAuthorizationError, match="multiple active"):
        await resolve_authenticated_context(FakeSession(multiple_rows), identity)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        await dependencies.get_authenticated_context(None, FakeSession([]))  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_or_unlinked_identity_maps_to_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invalid_identity(_token: str) -> OIDCIdentity:
        raise AuthenticationError("Invalid bearer token.")

    monkeypatch.setattr(dependencies, "verify_oidc_access_token", invalid_identity)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid")

    with pytest.raises(HTTPException) as invalid_exc:
        await dependencies.get_authenticated_context(credentials, FakeSession([]))  # type: ignore[arg-type]
    assert invalid_exc.value.status_code == 401
    assert invalid_exc.value.headers["WWW-Authenticate"] == "Bearer"

    async def valid_subject(_token: str) -> OIDCIdentity:
        return OIDCIdentity("https://issuer.example/", "unlinked-subject")

    monkeypatch.setattr(dependencies, "verify_oidc_access_token", valid_subject)
    with pytest.raises(HTTPException) as unlinked_exc:
        await dependencies.get_authenticated_context(credentials, FakeSession([]))  # type: ignore[arg-type]
    assert unlinked_exc.value.status_code == 401


@pytest.mark.asyncio
async def test_database_membership_overrides_role_and_scope_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = OIDCIdentity("https://issuer.example/", "external-user")

    async def verified_identity(_token: str) -> OIDCIdentity:
        return identity

    monkeypatch.setattr(dependencies, "verify_oidc_access_token", verified_identity)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="token-with-untrusted-admin-and-landlord-claims",
    )
    db = FakeSession(
        _membership_rows(
            user_id="11111111-2222-3333-4444-555555555555",
            role="CARETAKER",
            landlord_id=LANDLORD_A,
        )
    )

    context = await dependencies.get_authenticated_context(credentials, db)  # type: ignore[arg-type]

    assert context.role is Role.CARETAKER
    assert context.landlord_id == LANDLORD_A


@pytest.mark.asyncio
async def test_request_contexts_do_not_leak_membership_scope() -> None:
    identity = OIDCIdentity("https://issuer.example/", "same-provider-subject")
    context_a = await resolve_authenticated_context(
        FakeSession(
            _membership_rows(
                user_id="11111111-2222-3333-4444-555555555555",
                landlord_id=LANDLORD_A,
            )
        ),  # type: ignore[arg-type]
        identity,
    )
    context_b = await resolve_authenticated_context(
        FakeSession(
            _membership_rows(
                user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                landlord_id=LANDLORD_B,
            )
        ),  # type: ignore[arg-type]
        identity,
    )

    assert context_a.landlord_id == LANDLORD_A
    assert context_b.landlord_id == LANDLORD_B
    assert context_a.user_id != context_b.user_id


@pytest.mark.asyncio
async def test_unconfigured_oidc_returns_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unconfigured(_token: str) -> OIDCIdentity:
        raise AuthenticationConfigurationError("OIDC is not configured")

    monkeypatch.setattr(dependencies, "verify_oidc_access_token", unconfigured)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(HTTPException) as exc:
        await dependencies.get_authenticated_context(credentials, FakeSession([]))  # type: ignore[arg-type]

    assert exc.value.status_code == 503
