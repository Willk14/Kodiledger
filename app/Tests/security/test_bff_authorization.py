from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Depends, HTTPException, status
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials

from app.main import app
from app.security.dependencies import bearer_scheme, get_current_principal
from app.security.principals import AuthenticatedContext
from app.security.roles import Role


LANDLORD_SCOPE = "11111111-1111-1111-1111-111111111111"
TENANT_SCOPE = "55555555-5555-5555-5555-555555555555"


client = TestClient(app)
test_principals: dict[str, AuthenticatedContext] = {}


async def fake_authenticated_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedContext:
    if credentials is None or credentials.credentials not in test_principals:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return test_principals[credentials.credentials]


@pytest.fixture(autouse=True)
def override_authentication_for_authorization_tests():
    app.dependency_overrides[get_current_principal] = fake_authenticated_context
    yield
    app.dependency_overrides.pop(get_current_principal, None)
    test_principals.clear()


def make_token(
    *,
    user_id: str,
    role: str,
    landlord_id: str | None = LANDLORD_SCOPE,
    tenant_id: str | None = None,
) -> str:
    if role == "TENANT" and tenant_id is None:
        tenant_id = TENANT_SCOPE

    test_token = uuid4().hex
    test_principals[test_token] = AuthenticatedContext(
        user_id=user_id,
        role=Role(role),
        landlord_id=landlord_id,
        tenant_id=tenant_id,
    )
    return test_token


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


def test_unit_endpoints_require_authentication_and_reject_tenants():
    unit_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    unauthenticated = client.get(f"/api/v1/units/{unit_id}")
    token = make_token(user_id="tenant-user", role="TENANT")
    tenant = client.get(
        f"/api/v1/units/{unit_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthenticated.status_code == 401
    assert tenant.status_code == 403


def test_property_openapi_matches_documented_read_contract():
    paths = app.openapi()["paths"]
    collection = paths["/api/v1/properties"]
    detail = paths["/api/v1/properties/{property_id}"]

    assert set(collection) == {"get"}
    assert set(detail) == {"get"}
    assert collection["get"]["security"] == [{"HTTPBearer": []}]
    assert detail["get"]["security"] == [{"HTTPBearer": []}]
    assert collection["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "items": {"$ref": "#/components/schemas/PropertyRead"},
        "type": "array",
        "title": "Response List Properties Api V1 Properties Get",
    }
    assert detail["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PropertyRead"
    }
    assert {"401", "403", "500", "503"}.issubset(collection["get"]["responses"])
    assert {"401", "403", "404", "422", "500", "503"}.issubset(detail["get"]["responses"])
    assert "requestBody" not in collection["get"]
    assert "requestBody" not in detail["get"]


def test_unit_openapi_matches_documented_contract():
    paths = app.openapi()["paths"]
    property_units = paths["/api/v1/properties/{property_id}/units"]
    unit_detail = paths["/api/v1/units/{unit_id}"]

    assert set(property_units) == {"get", "post"}
    assert set(unit_detail) == {"get", "patch"}
    for operation in (*property_units.values(), *unit_detail.values()):
        assert operation["security"] == [{"HTTPBearer": []}]

    list_response = property_units["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert list_response["type"] == "array"
    assert list_response["items"]["$ref"] == "#/components/schemas/UnitRead"
    assert property_units["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UnitCreate"
    assert property_units["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UnitRead"
    assert unit_detail["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UnitRead"
    assert unit_detail["patch"]["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UnitUpdate"
    assert unit_detail["patch"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UnitRead"
    assert {"401", "403", "404", "422"}.issubset(property_units["get"]["responses"])
    assert {"401", "403", "404", "409", "422"}.issubset(property_units["post"]["responses"])
    assert {"401", "403", "404", "422"}.issubset(unit_detail["get"]["responses"])
    assert {"401", "403", "404", "409", "422"}.issubset(unit_detail["patch"]["responses"])


def test_tenant_openapi_matches_documented_contract():
    paths = app.openapi()["paths"]
    collection = paths["/api/v1/tenants"]
    detail = paths["/api/v1/tenants/{tenant_id}"]
    self_read = paths["/api/v1/tenants/me"]["get"]

    assert set(collection) == {"get", "post"}
    assert set(detail) == {"get"}
    operations = [collection["get"], collection["post"], detail["get"], self_read]
    for operation in operations:
        assert operation["security"] == [{"HTTPBearer": []}]

    assert collection["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"] == "#/components/schemas/TenantRead"
    assert collection["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/TenantCreate"
    assert collection["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/TenantRead"
    assert detail["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/TenantRead"
    assert self_read["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/TenantRead"
    assert {"401", "403", "500", "503"}.issubset(collection["get"]["responses"])
    assert {"401", "403", "404", "422", "500", "503"}.issubset(collection["post"]["responses"])
    assert {"401", "403", "404", "422", "500", "503"}.issubset(detail["get"]["responses"])
    assert {"401", "403", "404", "500", "503"}.issubset(self_read["responses"])
    assert "requestBody" not in collection["get"]
    assert "requestBody" not in detail["get"]
    assert "requestBody" not in self_read
    assert "patch" not in detail and "delete" not in detail


def test_tenant_management_rejects_unauthenticated_and_non_landlord_users():
    unauthenticated = client.get("/api/v1/tenants")
    token = make_token(user_id="tenant-user", role="TENANT")
    forbidden_list = client.get(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    forbidden_create = client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "unit_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "full_name": "Denied Tenant",
            "primary_phone": "254712345678",
            "lease_start_date": "2026-05-01",
        },
    )

    assert unauthenticated.status_code == 401
    assert forbidden_list.status_code == 403
    assert forbidden_create.status_code == 403


def test_invoice_endpoints_require_authentication_and_landlord_role():
    unauthenticated = client.get("/api/v1/invoices")
    token = make_token(user_id="tenant-user", role="TENANT")
    forbidden_list = client.get(
        "/api/v1/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    forbidden_create = client.post(
        "/api/v1/invoices",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert unauthenticated.status_code == 401
    assert forbidden_list.status_code == 403
    assert forbidden_create.status_code == 403


def test_invoice_openapi_matches_documented_contract():
    paths = app.openapi()["paths"]
    collection = paths["/api/v1/invoices"]
    detail = paths["/api/v1/invoices/{invoice_id}"]

    assert set(collection) == {"get", "post"}
    assert set(detail) == {"get"}
    operations = [collection["get"], collection["post"], detail["get"]]
    for operation in operations:
        assert operation["security"] == [{"HTTPBearer": []}]

    invoice_create = collection["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert invoice_create["$ref"] == "#/components/schemas/InvoiceCreate"
    assert collection["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"] == "#/components/schemas/InvoiceRead"
    assert collection["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/InvoiceRead"
    assert detail["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/InvoiceRead"
    create_properties = app.openapi()["components"]["schemas"]["InvoiceCreate"]["properties"]
    read_properties = app.openapi()["components"]["schemas"]["InvoiceRead"]["properties"]
    assert "total_amount" not in create_properties
    assert "is_paid" not in create_properties
    assert "landlord_id" not in create_properties
    assert "total_amount" in read_properties
    assert "is_paid" in read_properties
    assert "landlord_id" not in read_properties
    assert {"401", "403", "500", "503"}.issubset(collection["get"]["responses"])
    assert {"401", "403", "404", "409", "422", "500", "503"}.issubset(collection["post"]["responses"])
    assert {"401", "403", "404", "422", "500", "503"}.issubset(detail["get"]["responses"])
    assert "patch" not in detail and "delete" not in detail


def test_payment_read_routes_require_authentication_and_deny_caretakers():
    unauthenticated = client.get("/api/v1/payments")
    token = make_token(user_id="caretaker-user", role="CARETAKER")
    forbidden = client.get(
        "/api/v1/payments",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403


def test_payment_openapi_matches_documented_read_contract():
    paths = app.openapi()["paths"]
    collection = paths["/api/v1/payments"]
    detail = paths["/api/v1/payments/{payment_id}"]

    assert set(collection) == {"get"}
    assert set(detail) == {"get"}
    assert collection["get"]["security"] == [{"HTTPBearer": []}]
    assert detail["get"]["security"] == [{"HTTPBearer": []}]
    assert collection["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"] == "#/components/schemas/PaymentTransactionRead"
    assert detail["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/PaymentTransactionRead"
    fields = app.openapi()["components"]["schemas"]["PaymentTransactionRead"]["properties"]
    assert set(fields) == {
        "id",
        "tenant_id",
        "mpesa_receipt_number",
        "amount",
        "payment_method",
        "status",
        "created_at",
        "completed_at",
    }
    assert {"401", "403", "500", "503"}.issubset(collection["get"]["responses"])
    assert {"401", "403", "404", "422", "500", "503"}.issubset(detail["get"]["responses"])
    assert "post" not in collection and "patch" not in detail and "delete" not in detail


# ============================================================
# Landlord Authorization
# ============================================================


def test_landlord_can_access_landlord_endpoint():
    user_id = str(uuid4())
    token = make_token(
        user_id=user_id,
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

    assert data["user_id"] == user_id
    assert data["role"] == "LANDLORD"
    assert data["landlord_id"] == LANDLORD_SCOPE


def test_landlord_openapi_matches_context_contract():
    operation = app.openapi()["paths"]["/api/v1/bff/landlord/me"]["get"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/LandlordContextRead"
    }
    assert {"401", "403", "500", "503"}.issubset(operation["responses"])
    assert not operation.get("parameters")
    assert "requestBody" not in operation


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
    assert data["landlord_id"] == LANDLORD_SCOPE


def test_request_scope_parameters_cannot_override_authenticated_principal():
    token = make_token(user_id="caretaker-user", role="CARETAKER")
    response = client.get(
        "/api/v1/bff/caretaker/me",
        params={
            "landlord_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "tenant_id": TENANT_SCOPE,
            "role": "ADMIN",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "caretaker-user",
        "role": "CARETAKER",
        "landlord_id": LANDLORD_SCOPE,
    }


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
