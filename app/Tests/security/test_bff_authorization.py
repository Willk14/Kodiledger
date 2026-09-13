from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.security.authentication import create_access_token


client = TestClient(app)


def make_token(
    *,
    user_id: str,
    role: str,
    landlord_id: str | None = None,
) -> str:
    """
    Create a test JWT.

    Current create_access_token() accepts user_id and role.
    landlord_id will be added to the token once the
    authentication model is extended to include tenant scope.
    """
    return create_access_token(
        user_id=user_id,
        role=role,
    )


# ============================================================
# Authentication
# ============================================================


def test_landlord_endpoint_requires_authentication():
    response = client.get(
        "/api/v1/bff/landlord/me"
    )

    assert response.status_code == 401


def test_caretaker_endpoint_requires_authentication():
    response = client.get(
        "/api/v1/bff/caretaker/me"
    )

    assert response.status_code == 401


# ============================================================
# Landlord Authorization
# ============================================================


def test_landlord_can_access_landlord_endpoint():
    token = make_token(
        user_id="landlord-user",
        role="LANDLORD",
    )

    response = client.get(
        "/api/v1/bff/landlord/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["user_id"] == "landlord-user"
    assert data["role"] == "LANDLORD"


def test_caretaker_cannot_access_landlord_endpoint():
    token = make_token(
        user_id="caretaker-user",
        role="CARETAKER",
    )

    response = client.get(
        "/api/v1/bff/landlord/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 403


# ============================================================
# Caretaker Authorization
# ============================================================


def test_caretaker_can_access_caretaker_endpoint():
    token = make_token(
        user_id="caretaker-user",
        role="CARETAKER",
    )

    response = client.get(
        "/api/v1/bff/caretaker/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["user_id"] == "caretaker-user"
    assert data["role"] == "CARETAKER"


def test_landlord_cannot_access_caretaker_endpoint():
    token = make_token(
        user_id="landlord-user",
        role="LANDLORD",
    )

    response = client.get(
        "/api/v1/bff/caretaker/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 403


# ============================================================
# Tenant Authorization
# ============================================================


def test_tenant_cannot_access_landlord_endpoint():
    token = make_token(
        user_id="tenant-user",
        role="TENANT",
    )

    response = client.get(
        "/api/v1/bff/landlord/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 403


def test_tenant_cannot_access_caretaker_endpoint():
    token = make_token(
        user_id="tenant-user",
        role="TENANT",
    )

    response = client.get(
        "/api/v1/bff/caretaker/me",
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert response.status_code == 403


# ============================================================
# Invalid Authentication
# ============================================================


def test_invalid_token_is_rejected():
    response = client.get(
        "/api/v1/bff/landlord/me",
        headers={
            "Authorization": "Bearer invalid-token"
        },
    )

    assert response.status_code == 401


def test_malformed_authorization_header_is_rejected():
    response = client.get(
        "/api/v1/bff/landlord/me",
        headers={
            "Authorization": "NotBearer token"
        },
    )

    assert response.status_code == 401
    