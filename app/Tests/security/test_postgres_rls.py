from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import get_db
from app.main import app as api_app
from app.repositories.ledger_repository import LedgerRepository
from app.repositories.outbox_event_repository import OutboxEventRepository
import app.security.authentication as authentication
from app.security.dependencies import get_current_principal
from app.security.principals import Principal
from app.security.rls import get_rls_db, set_rls_context
from app.security.roles import Role
from app.services.invoice_allocation_service import AllocationConflict
from app.services.unassigned_payment_resolution_service import UnassignedPaymentResolutionService
from app.Tests.rls_test_database import initialize


ENV_FILE = Path(__file__).resolve().parents[3] / ".env.rls-test"


@dataclass(frozen=True)
class Owner:
    landlord_id: UUID
    user_id: UUID
    membership_id: UUID
    property_id: UUID
    unit_id: UUID
    tenant_id: UUID
    invoice_id: UUID
    payment_id: UUID
    ledger_id: UUID

    @property
    def principal(self) -> Principal:
        return Principal(
            user_id=str(self.user_id),
            role=Role.LANDLORD,
            landlord_id=str(self.landlord_id),
        )


@pytest.fixture(scope="session")
def rls_test_config() -> dict[str, str]:
    values = {key: value for key, value in dotenv_values(ENV_FILE).items() if value}
    if not values.get("RLS_TEST_DATABASE_URL"):
        pytest.skip("RLS integration database is not configured; see .env.example and .env.rls-test setup.")
    # Run the database/role safety assertions before any test fixture writes data.
    asyncio.run(initialize())
    return values  # type: ignore[return-value]


@pytest_asyncio.fixture
async def rls_database(rls_test_config: dict[str, str]):
    app_url = make_url(rls_test_config["RLS_TEST_DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    admin_url = make_url(rls_test_config["RLS_TEST_ADMIN_DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    app_engine = create_async_engine(app_url, pool_size=2, max_overflow=0, pool_pre_ping=True)
    admin_engine = create_async_engine(admin_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    app_sessions = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)

    a = Owner(*(uuid4() for _ in range(9)))
    b = Owner(*(uuid4() for _ in range(9)))
    owners = (a, b)

    async with admin_engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO landlords (id, full_name, email, phone_number)
            VALUES (:landlord_id, :name, :email, :phone)
        """), [
            {"landlord_id": owner.landlord_id, "name": f"RLS Owner {index}",
             "email": f"rls-{owner.landlord_id}@example.test", "phone": f"254700{owner.landlord_id.int % 1000000:06d}"}
            for index, owner in enumerate(owners)
        ])
        for index, owner in enumerate(owners):
            await connection.execute(text("""
                INSERT INTO app_users (id, identity_issuer, identity_subject)
                VALUES (:id, 'https://rls-test.invalid/', :subject)
            """), {"id": owner.user_id, "subject": f"owner-{index}-{owner.user_id}"})
            await connection.execute(text("""
                INSERT INTO user_memberships (id, user_id, role, landlord_id)
                VALUES (:membership_id, :id, 'LANDLORD', :landlord_id)
            """), {"id": owner.user_id, "membership_id": owner.membership_id,
                  "landlord_id": owner.landlord_id})
            await connection.execute(text("""
                INSERT INTO properties (id, landlord_id, name, county, town_location, total_units)
                VALUES (:id, :landlord_id, :name, 'Test County', 'Test Town', 1)
            """), {"id": owner.property_id, "landlord_id": owner.landlord_id, "name": f"RLS Property {index}"})
            await connection.execute(text("""
                INSERT INTO units (id, property_id, landlord_id, unit_number, base_rent)
                VALUES (:id, :property_id, :landlord_id, 'A1', 12000)
            """), {"id": owner.unit_id, "property_id": owner.property_id, "landlord_id": owner.landlord_id})
            await connection.execute(text("""
                INSERT INTO tenants (id, landlord_id, unit_id, full_name, primary_phone, lease_start_date)
                VALUES (:id, :landlord_id, :unit_id, 'RLS Tenant', :phone, :lease_date)
            """), {"id": owner.tenant_id, "landlord_id": owner.landlord_id, "unit_id": owner.unit_id,
                  "phone": f"254711{owner.landlord_id.int % 1000000:06d}", "lease_date": date(2026, 1, 1)})
            await connection.execute(text("""
                INSERT INTO invoices (id, landlord_id, unit_id, tenant_id, invoice_number,
                                      billing_month, rent_amount, due_date)
                VALUES (:id, :landlord_id, :unit_id, :tenant_id, :invoice_no,
                        DATE '2026-01-01', 12000, DATE '2026-01-05')
            """), {"id": owner.invoice_id, "landlord_id": owner.landlord_id, "unit_id": owner.unit_id,
                  "tenant_id": owner.tenant_id, "invoice_no": f"RLS-{owner.invoice_id}"})
            await connection.execute(text("""
                INSERT INTO payment_transactions (id, landlord_id, tenant_id, mpesa_receipt_number,
                                                  amount, payment_method, status)
                VALUES (:id, :landlord_id, :tenant_id, :receipt, 12000, 'MPESA_STK_PUSH', 'COMPLETED')
            """), {"id": owner.payment_id, "landlord_id": owner.landlord_id, "tenant_id": owner.tenant_id,
                  "receipt": f"RLS-{owner.payment_id}"})
            await connection.execute(text("""
                INSERT INTO ledger_entries (id, landlord_id, unit_id, tenant_id, invoice_id,
                                            payment_transaction_id, mpesa_receipt_number, entry_type, amount,
                                            payment_method, status, description)
                VALUES (:id, :landlord_id, :unit_id, :tenant_id, :invoice_id, :payment_id,
                        :receipt, 'CREDIT', 12000, 'MPESA_STK_PUSH', 'COMPLETED', 'RLS integration fixture')
            """), {"id": owner.ledger_id, "landlord_id": owner.landlord_id, "unit_id": owner.unit_id,
                  "tenant_id": owner.tenant_id, "invoice_id": owner.invoice_id, "payment_id": owner.payment_id,
                  "receipt": f"RLS-{owner.payment_id}"})

    try:
        yield {"a": a, "b": b, "engine": app_engine, "sessions": app_sessions,
               "admin_engine": admin_engine, "system_url": rls_test_config["RLS_TEST_SYSTEM_DATABASE_URL"]}
    finally:
        async with admin_engine.begin() as connection:
            for owner in owners:
                for table in ("ledger_entries", "payment_transactions", "invoices", "tenants", "units", "properties"):
                    await connection.execute(text(f"DELETE FROM {table} WHERE landlord_id = :landlord_id"),
                                             {"landlord_id": owner.landlord_id})
                await connection.execute(text("DELETE FROM user_memberships WHERE id = :id"), {"id": owner.membership_id})
                await connection.execute(text("DELETE FROM app_users WHERE id = :id"), {"id": owner.user_id})
                await connection.execute(text("DELETE FROM landlords WHERE id = :id"), {"id": owner.landlord_id})
        await app_engine.dispose()
        await admin_engine.dispose()


async def _visible_ids(sessions, principal: Principal, table: str) -> set[UUID]:
    async with sessions() as session:
        async with session.begin():
            await set_rls_context(session, principal)
            rows = await session.execute(text(f"SELECT id FROM {table}"))
            return set(rows.scalars().all())


@pytest.mark.asyncio
async def test_postgres_rls_reads_only_authenticated_landlord_rows(rls_database):
    a, b = rls_database["a"], rls_database["b"]
    assert await _visible_ids(rls_database["sessions"], a.principal, "invoices") == {a.invoice_id}
    assert await _visible_ids(rls_database["sessions"], a.principal, "payment_transactions") == {a.payment_id}
    assert await _visible_ids(rls_database["sessions"], a.principal, "ledger_entries") == {a.ledger_id}
    assert await _visible_ids(rls_database["sessions"], b.principal, "invoices") == {b.invoice_id}
    assert await _visible_ids(rls_database["sessions"], b.principal, "payment_transactions") == {b.payment_id}
    assert await _visible_ids(rls_database["sessions"], b.principal, "ledger_entries") == {b.ledger_id}


@pytest.mark.asyncio
async def test_payment_credit_application_rls_scopes_reads_and_inserts(rls_database):
    owner_a, owner_b = rls_database["a"], rls_database["b"]
    credit_a_read, credit_a_insert = uuid4(), uuid4()
    credit_b_read, credit_b_insert = uuid4(), uuid4()
    application_a, application_b = uuid4(), uuid4()
    application_allowed = uuid4()

    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text("""
            INSERT INTO payment_credits (id, payment_transaction_id, tenant_id, amount)
            VALUES
                (:credit_a_read, :payment_a, :tenant_a, 100),
                (:credit_a_insert, :payment_a, :tenant_a, 100),
                (:credit_b_read, :payment_b, :tenant_b, 100),
                (:credit_b_insert, :payment_b, :tenant_b, 100)
        """), {
            "credit_a_read": credit_a_read,
            "credit_a_insert": credit_a_insert,
            "payment_a": owner_a.payment_id,
            "tenant_a": owner_a.tenant_id,
            "credit_b_read": credit_b_read,
            "credit_b_insert": credit_b_insert,
            "payment_b": owner_b.payment_id,
            "tenant_b": owner_b.tenant_id,
        })
        await connection.execute(text("""
            INSERT INTO payment_credit_applications
                (id, payment_credit_id, invoice_id, amount, application_key)
            VALUES
                (:application_a, :credit_a, :invoice_a, 25, :key_a),
                (:application_b, :credit_b, :invoice_b, 25, :key_b)
        """), {
            "application_a": application_a,
            "credit_a": credit_a_read,
            "invoice_a": owner_a.invoice_id,
            "key_a": f"rls-read-a-{application_a}",
            "application_b": application_b,
            "credit_b": credit_b_read,
            "invoice_b": owner_b.invoice_id,
            "key_b": f"rls-read-b-{application_b}",
        })

    try:
        sessions = rls_database["sessions"]
        assert await _visible_ids(sessions, owner_a.principal, "payment_credit_applications") == {
            application_a
        }
        assert await _visible_ids(sessions, owner_b.principal, "payment_credit_applications") == {
            application_b
        }

        async with sessions() as session, session.begin():
            await set_rls_context(session, owner_a.principal)
            await session.execute(text("""
                INSERT INTO payment_credit_applications
                    (id, payment_credit_id, invoice_id, amount, application_key)
                VALUES (:id, :credit_id, :invoice_id, 10, :key)
            """), {
                "id": application_allowed,
                "credit_id": credit_a_insert,
                "invoice_id": owner_a.invoice_id,
                "key": f"rls-allowed-a-{application_allowed}",
            })

        with pytest.raises(DBAPIError):
            async with sessions() as session, session.begin():
                await set_rls_context(session, owner_a.principal)
                await session.execute(text("""
                    INSERT INTO payment_credit_applications
                        (id, payment_credit_id, invoice_id, amount, application_key)
                    VALUES (:id, :credit_id, :invoice_id, 10, :key)
                """), {
                    "id": uuid4(),
                    "credit_id": credit_b_insert,
                    "invoice_id": owner_b.invoice_id,
                    "key": f"rls-denied-a-to-b-{uuid4()}",
                })

        assert await _visible_ids(sessions, owner_a.principal, "payment_credit_applications") == {
            application_a,
            application_allowed,
        }
        assert await _visible_ids(sessions, owner_b.principal, "payment_credit_applications") == {
            application_b
        }
    finally:
        async with rls_database["admin_engine"].begin() as connection:
            await connection.execute(text("""
                DELETE FROM payment_credit_applications
                WHERE id = ANY(:ids)
            """), {"ids": [application_a, application_b, application_allowed]})
            await connection.execute(text("""
                DELETE FROM payment_credits
                WHERE id = ANY(:ids)
            """), {"ids": [credit_a_read, credit_a_insert, credit_b_read, credit_b_insert]})


@pytest.mark.asyncio
async def test_postgres_rls_denies_cross_landlord_financial_mutations(rls_database):
    b = rls_database["b"]
    sessions = rls_database["sessions"]
    async with sessions() as session, session.begin():
        await set_rls_context(session, rls_database["a"].principal)
        update_result = await session.execute(
            text("UPDATE invoices SET rent_amount = 1 WHERE id = :id"), {"id": b.invoice_id}
        )
        delete_result = await session.execute(
            text("DELETE FROM invoices WHERE id = :id"), {"id": b.invoice_id}
        )
        assert update_result.rowcount == 0
        assert delete_result.rowcount == 0

    async with sessions() as session:
        with pytest.raises(DBAPIError):
            async with session.begin():
                await set_rls_context(session, rls_database["a"].principal)
                await session.execute(text("""
                    INSERT INTO properties (id, landlord_id, name, county, total_units)
                    VALUES (:id, :landlord_id, 'forbidden', 'Test County', 1)
                """), {"id": uuid4(), "landlord_id": b.landlord_id})


@pytest.mark.asyncio
async def test_get_rls_db_binds_principal_context_to_actual_postgresql_session(rls_database):
    owner = rls_database["a"]
    async with rls_database["sessions"]() as session:
        async with session.begin():
            bound = await get_rls_db(db=session, principal=owner.principal)
            row = (await bound.execute(text("""
                SELECT current_setting('app.current_user_id', true),
                       current_setting('app.current_landlord_id', true),
                       current_setting('app.current_role', true),
                       count(*) FROM properties
            """))).one()
            assert row[0] == str(owner.user_id)
            assert row[1] == str(owner.landlord_id)
            assert row[2] == "LANDLORD"
            assert row[3] == 1


@pytest.mark.asyncio
async def test_authenticated_oidc_request_resolves_membership_and_enforces_rls(
    rls_database,
    monkeypatch: pytest.MonkeyPatch,
):
    owner = rls_database["a"]
    other_owner = rls_database["b"]
    foreign_unassigned = await _insert_unassigned_payment(rls_database, other_owner)
    issuer = "https://rls-test.invalid/"
    audience = "kodiledger-api"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "iss": issuer,
            "sub": f"owner-0-{owner.user_id}",
            "aud": audience,
            "exp": now + 300,
            "iat": now,
            # Deliberately untrusted claims: local membership must win.
            "role": "ADMIN",
            "landlord_id": str(other_owner.landlord_id),
        },
        private_key,
        algorithm="RS256",
    )

    class TestJwksClient:
        def get_signing_key_from_jwt(self, _token: str):
            return SimpleNamespace(key=private_key.public_key())

    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", issuer)
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", audience)
    monkeypatch.setattr(settings, "OIDC_JWKS_URL", "https://rls-test.invalid/jwks")
    monkeypatch.setattr(settings, "OIDC_SIGNING_ALGORITHMS", "RS256")
    monkeypatch.setattr(
        authentication,
        "_jwks_client",
        lambda _url, _timeout: TestJwksClient(),
    )

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_override = api_app.dependency_overrides.get(get_db)
    api_app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/bff/landlord/me",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "landlord_id": str(other_owner.landlord_id),
                    "role": "ADMIN",
                },
            )
            properties_response = await client.get(
                "/api/v1/properties",
                headers={"Authorization": f"Bearer {token}"},
                params={"landlord_id": str(other_owner.landlord_id)},
            )
            foreign_resolution = await client.post(
                f"/api/v1/unassigned-payments/{foreign_unassigned['id']}/resolve",
                headers={"Authorization": f"Bearer {token}"},
                params={"landlord_id": str(other_owner.landlord_id)},
                json={"tenant_id": str(other_owner.tenant_id)},
            )
    finally:
        if previous_override is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_override
        await _delete_unassigned_fixture(rls_database, foreign_unassigned)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user_id", "role", "landlord_id", "property_count"}
    assert body["user_id"] == str(owner.user_id)
    assert body["role"] == "LANDLORD"
    assert body["landlord_id"] == str(owner.landlord_id)
    # Each landlord has one fixture property; without RLS the count would be two.
    assert body["property_count"] == 1
    assert properties_response.status_code == 200
    assert [row["id"] for row in properties_response.json()] == [
        str(owner.property_id)
    ]
    # The JWT says ADMIN and names the other landlord, but active membership
    # remains authoritative for the allocation command as well.
    assert foreign_resolution.status_code == 404


@pytest.mark.asyncio
async def test_property_api_lists_and_reads_only_authenticated_landlord_rows(
    rls_database,
):
    owner = rls_database["a"]
    other_owner = rls_database["b"]

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: owner.principal
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            listing = await client.get("/api/v1/properties")
            own_property = await client.get(
                f"/api/v1/properties/{owner.property_id}"
            )
            foreign_property = await client.get(
                f"/api/v1/properties/{other_owner.property_id}"
            )
            invalid_id = await client.get("/api/v1/properties/not-a-uuid")
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [str(owner.property_id)]
    assert set(listing.json()[0]) == {
        "id",
        "name",
        "county",
        "town_location",
        "total_units",
        "created_at",
    }
    assert listing.json()[0]["name"] == "RLS Property 0"
    assert own_property.status_code == 200
    assert own_property.json()["id"] == str(owner.property_id)
    assert foreign_property.status_code == 404
    assert foreign_property.json() == {"detail": "Property not found."}
    assert invalid_id.status_code == 422


@pytest.mark.asyncio
async def test_property_api_rejects_wrong_role_and_missing_bearer(rls_database):
    owner = rls_database["a"]
    tenant_principal = Principal(
        user_id=str(uuid4()),
        role=Role.TENANT,
        landlord_id=str(owner.landlord_id),
        tenant_id=str(owner.tenant_id),
    )

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: tenant_principal
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            forbidden = await client.get("/api/v1/properties")
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    api_app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            unauthenticated = await client.get("/api/v1/properties")
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db

    assert forbidden.status_code == 403
    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def test_unit_api_enforces_landlord_scope_and_supports_management(rls_database):
    owner = rls_database["a"]
    other_owner = rls_database["b"]
    active_principal = owner.principal

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: active_principal
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            listing = await client.get(
                f"/api/v1/properties/{owner.property_id}/units"
            )
            own_unit = await client.get(f"/api/v1/units/{owner.unit_id}")
            foreign_unit = await client.get(f"/api/v1/units/{other_owner.unit_id}")
            foreign_owner_update = await client.patch(
                f"/api/v1/units/{other_owner.unit_id}",
                json={"base_rent": "1.00"},
            )
            created = await client.post(
                f"/api/v1/properties/{owner.property_id}/units",
                json={"unit_number": "B2", "base_rent": "1234.56"},
            )
            assert created.status_code == 201
            unit_id = created.json()["id"]
            property_after_create = await client.get(
                f"/api/v1/properties/{owner.property_id}"
            )
            updated = await client.patch(
                f"/api/v1/units/{unit_id}",
                json={"base_rent": "1400.00"},
            )
            duplicate = await client.post(
                f"/api/v1/properties/{owner.property_id}/units",
                json={"unit_number": "B2", "base_rent": "1500.00"},
            )
            property_after_conflict = await client.get(
                f"/api/v1/properties/{owner.property_id}"
            )
            foreign_property_create = await client.post(
                f"/api/v1/properties/{other_owner.property_id}/units",
                json={"unit_number": "B2", "base_rent": "1500.00"},
            )
            active_principal = other_owner.principal
            foreign_owner_read = await client.get(f"/api/v1/units/{unit_id}")
            foreign_owner_update = await client.patch(
                f"/api/v1/units/{unit_id}",
                json={"base_rent": "1.00"},
            )
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [str(owner.unit_id)]
    assert own_unit.status_code == 200
    assert own_unit.json()["base_rent"] == "12000.00"
    assert foreign_unit.status_code == 404
    assert foreign_owner_update.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["base_rent"] == "1400.00"
    assert property_after_create.status_code == 200
    assert property_after_create.json()["total_units"] == 2
    assert duplicate.status_code == 409
    assert property_after_conflict.status_code == 200
    assert property_after_conflict.json()["total_units"] == 2
    assert foreign_property_create.status_code == 404
    assert foreign_owner_read.status_code == 404


@pytest.mark.asyncio
async def test_unit_api_allows_caretaker_reads_but_denies_writes(rls_database):
    owner = rls_database["a"]
    caretaker = Principal(
        user_id=str(uuid4()),
        role=Role.CARETAKER,
        landlord_id=str(owner.landlord_id),
    )

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: caretaker
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            listing = await client.get(
                f"/api/v1/properties/{owner.property_id}/units"
            )
            write = await client.patch(
                f"/api/v1/units/{owner.unit_id}",
                json={"base_rent": "12500.00"},
            )
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [str(owner.unit_id)]
    assert write.status_code == 403


@pytest.mark.asyncio
async def test_tenant_api_enforces_landlord_scope_and_tenant_self_scope(rls_database):
    owner = rls_database["a"]
    other_owner = rls_database["b"]
    active_principal = owner.principal

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: active_principal
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            listing = await client.get("/api/v1/tenants")
            own_tenant = await client.get(f"/api/v1/tenants/{owner.tenant_id}")
            foreign_tenant = await client.get(
                f"/api/v1/tenants/{other_owner.tenant_id}"
            )
            created = await client.post(
                "/api/v1/tenants",
                json={
                    "unit_id": str(owner.unit_id),
                    "full_name": "  New   Tenant ",
                    "primary_phone": "254712345678",
                    "id_number": "ID-123",
                    "lease_start_date": "2026-05-01",
                    "deposit_amount": "15000.25",
                },
            )
            occupied_unit = await client.get(f"/api/v1/units/{owner.unit_id}")
            foreign_unit_create = await client.post(
                "/api/v1/tenants",
                json={
                    "unit_id": str(other_owner.unit_id),
                    "full_name": "Foreign Tenant",
                    "primary_phone": "254712345679",
                    "lease_start_date": "2026-05-01",
                },
            )
            client_supplied_scope = await client.post(
                "/api/v1/tenants",
                json={
                    "unit_id": str(owner.unit_id),
                    "landlord_id": str(other_owner.landlord_id),
                    "full_name": "Forged Scope Tenant",
                    "primary_phone": "254712345681",
                    "lease_start_date": "2026-05-01",
                },
            )
            active_principal = Principal(
                user_id=str(uuid4()),
                role=Role.TENANT,
                landlord_id=str(owner.landlord_id),
                tenant_id=str(owner.tenant_id),
            )
            self_tenant = await client.get("/api/v1/tenants/me")
            active_principal = Principal(
                user_id=str(uuid4()),
                role=Role.TENANT,
                landlord_id=str(owner.landlord_id),
                tenant_id=str(other_owner.tenant_id),
            )
            mismatched_self = await client.get("/api/v1/tenants/me")
            active_principal = Principal(
                user_id=str(uuid4()),
                role=Role.CARETAKER,
                landlord_id=str(owner.landlord_id),
            )
            caretaker_listing = await client.get("/api/v1/tenants")
            caretaker_create = await client.post(
                "/api/v1/tenants",
                json={
                    "unit_id": str(owner.unit_id),
                    "full_name": "Denied Tenant",
                    "primary_phone": "254712345680",
                    "lease_start_date": "2026-05-01",
                },
            )
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [str(owner.tenant_id)]
    assert own_tenant.status_code == 200
    assert foreign_tenant.status_code == 404
    assert created.status_code == 201
    assert created.json()["full_name"] == "New Tenant"
    assert created.json()["deposit_amount"] == "15000.25"
    assert "id_number" not in created.json()
    assert occupied_unit.status_code == 200
    assert occupied_unit.json()["is_occupied"] is False
    assert foreign_unit_create.status_code == 404
    assert client_supplied_scope.status_code == 422
    assert self_tenant.status_code == 200
    assert self_tenant.json()["id"] == str(owner.tenant_id)
    assert mismatched_self.status_code == 404
    assert caretaker_listing.status_code == 200
    assert caretaker_create.status_code == 403


@pytest.mark.asyncio
async def test_invoice_api_enforces_landlord_rls_and_tenant_unit_consistency(rls_database):
    owner = rls_database["a"]
    other_owner = rls_database["b"]
    alternate_unit_id = uuid4()
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO units (id, property_id, landlord_id, unit_number, base_rent)
                VALUES (:id, :property_id, :landlord_id, 'A2', 12000)
                """
            ),
            {
                "id": alternate_unit_id,
                "property_id": owner.property_id,
                "landlord_id": owner.landlord_id,
            },
        )

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: owner.principal

    def payload(
        unit_id: UUID,
        tenant_id: UUID,
        invoice_number: str,
    ) -> dict[str, object]:
        return {
            "unit_id": str(unit_id),
            "tenant_id": str(tenant_id),
            "invoice_number": invoice_number,
            "billing_month": "2026-10-01",
            "rent_amount": "12000.00",
            "water_amount": "30.00",
            "garbage_amount": "50.00",
            "security_amount": "60.00",
            "due_date": "2026-10-05",
        }

    invoice_number = f"RLS-API-{uuid4()}"
    valid_payload = payload(owner.unit_id, owner.tenant_id, invoice_number)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            created = await client.post("/api/v1/invoices", json=valid_payload)
            listing = await client.get("/api/v1/invoices")
            own_invoice = await client.get(
                f"/api/v1/invoices/{owner.invoice_id}"
            )
            foreign_invoice = await client.get(
                f"/api/v1/invoices/{other_owner.invoice_id}"
            )
            duplicate = await client.post(
                "/api/v1/invoices",
                json=valid_payload,
            )
            listing_after_conflict = await client.get("/api/v1/invoices")
            same_landlord_wrong_unit = await client.post(
                "/api/v1/invoices",
                json=payload(alternate_unit_id, owner.tenant_id, f"{invoice_number}-B"),
            )
            foreign_tenant_own_unit = await client.post(
                "/api/v1/invoices",
                json=payload(owner.unit_id, other_owner.tenant_id, f"{invoice_number}-C"),
            )
            own_tenant_foreign_unit = await client.post(
                "/api/v1/invoices",
                json=payload(other_owner.unit_id, owner.tenant_id, f"{invoice_number}-D"),
            )
            foreign_tenant_foreign_unit = await client.post(
                "/api/v1/invoices",
                json=payload(other_owner.unit_id, other_owner.tenant_id, f"{invoice_number}-E"),
            )
            forged_scope = payload(owner.unit_id, owner.tenant_id, f"{invoice_number}-F")
            forged_scope["landlord_id"] = str(other_owner.landlord_id)
            client_scope = await client.post("/api/v1/invoices", json=forged_scope)
            forged_total = payload(owner.unit_id, owner.tenant_id, f"{invoice_number}-G")
            forged_total["total_amount"] = "0.00"
            client_total = await client.post("/api/v1/invoices", json=forged_total)
            forged_paid = payload(owner.unit_id, owner.tenant_id, f"{invoice_number}-H")
            forged_paid["is_paid"] = True
            client_paid = await client.post("/api/v1/invoices", json=forged_paid)
            negative_amount = payload(owner.unit_id, owner.tenant_id, f"{invoice_number}-I")
            negative_amount["rent_amount"] = "-0.01"
            negative = await client.post("/api/v1/invoices", json=negative_amount)
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert created.status_code == 201
    assert created.json()["total_amount"] == "12140.00"
    assert created.json()["is_paid"] is False
    assert "landlord_id" not in created.json()
    assert "total_amount" not in valid_payload
    assert listing.status_code == 200
    listed_ids = {invoice["id"] for invoice in listing.json()}
    assert str(owner.invoice_id) in listed_ids
    assert str(other_owner.invoice_id) not in listed_ids
    assert created.json()["id"] in listed_ids
    assert {invoice["id"] for invoice in listing_after_conflict.json()} == listed_ids
    assert own_invoice.status_code == 200
    assert foreign_invoice.status_code == 404
    assert duplicate.status_code == 409
    assert same_landlord_wrong_unit.status_code == 404
    assert foreign_tenant_own_unit.status_code == 404
    assert own_tenant_foreign_unit.status_code == 404
    assert foreign_tenant_foreign_unit.status_code == 404
    assert client_scope.status_code == 422
    assert client_total.status_code == 422
    assert client_paid.status_code == 422
    assert negative.status_code == 422


@pytest.mark.asyncio
async def test_payment_history_api_enforces_landlord_and_tenant_scope(rls_database):
    owner = rls_database["a"]
    other_owner = rls_database["b"]
    active_principal = owner.principal

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: active_principal
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            landlord_list = await client.get("/api/v1/payments")
            landlord_own = await client.get(
                f"/api/v1/payments/{owner.payment_id}"
            )
            landlord_foreign = await client.get(
                f"/api/v1/payments/{other_owner.payment_id}"
            )
            active_principal = Principal(
                user_id=str(uuid4()),
                role=Role.TENANT,
                landlord_id=str(owner.landlord_id),
                tenant_id=str(owner.tenant_id),
            )
            tenant_list = await client.get("/api/v1/payments")
            tenant_own = await client.get(
                f"/api/v1/payments/{owner.payment_id}"
            )
            tenant_foreign = await client.get(
                f"/api/v1/payments/{other_owner.payment_id}"
            )
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert landlord_list.status_code == 200
    assert [row["id"] for row in landlord_list.json()] == [str(owner.payment_id)]
    assert landlord_own.status_code == 200
    assert landlord_foreign.status_code == 404
    assert tenant_list.status_code == 200
    assert [row["id"] for row in tenant_list.json()] == [str(owner.payment_id)]
    assert tenant_own.status_code == 200
    assert tenant_foreign.status_code == 404
    assert set(tenant_own.json()) == {
        "id",
        "tenant_id",
        "mpesa_receipt_number",
        "amount",
        "payment_method",
        "status",
        "created_at",
        "completed_at",
    }


@pytest.mark.asyncio
async def test_missing_or_unmatched_landlord_context_exposes_no_rows(rls_database):
    async with rls_database["sessions"]() as session:
        async with session.begin():
            assert (await session.execute(text("SELECT id FROM invoices"))).all() == []
            await session.execute(text("SELECT set_config('app.current_landlord_id', :id, true)"),
                                  {"id": str(uuid4())})
            assert (await session.execute(text("SELECT id FROM invoices"))).all() == []


@pytest.mark.asyncio
async def test_sequential_transactions_on_same_pooled_connection_do_not_leak_context(rls_database):
    engine = rls_database["engine"]
    sessions = rls_database["sessions"]
    a, b = rls_database["a"], rls_database["b"]
    async with sessions() as session:
        async with session.begin():
            first_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await set_rls_context(session, a.principal)
            assert (await session.execute(text("SELECT id FROM invoices"))).scalars().all() == [a.invoice_id]
        async with session.begin():
            second_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            assert second_pid == first_pid
            assert await session.scalar(text("SELECT current_setting('app.current_landlord_id', true)")) in (None, "")
            await set_rls_context(session, b.principal)
            assert (await session.execute(text("SELECT id FROM invoices"))).scalars().all() == [b.invoice_id]
    assert engine.pool.size() == 2


@pytest.mark.asyncio
async def test_concurrent_landlord_requests_remain_isolated_across_pool(rls_database):
    a, b = rls_database["a"], rls_database["b"]

    async def request(owner: Owner) -> set[UUID]:
        await asyncio.sleep(0)
        return await _visible_ids(rls_database["sessions"], owner.principal, "invoices")

    result_a, result_b = await asyncio.gather(request(a), request(b))
    assert result_a == {a.invoice_id}
    assert result_b == {b.invoice_id}


@pytest.mark.asyncio
async def test_system_session_remains_separate_and_bypasses_rls(rls_database):
    system_url = make_url(rls_database["system_url"]).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(system_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            row = (await connection.execute(text("""
                SELECT current_user,
                       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user),
                       (SELECT count(*) FROM invoices
                        WHERE landlord_id IN (:landlord_a, :landlord_b))
            """), {
                "landlord_a": rls_database["a"].landlord_id,
                "landlord_b": rls_database["b"].landlord_id,
            })).one()
        assert row[0] == "kodiflow_system"
        assert row[1] is True
        assert row[2] == 2
    finally:
        await engine.dispose()


async def _insert_unassigned_payment(rls_database, owner: Owner, amount: int = 15000):
    raw_webhook_id = uuid4()
    payment_id = uuid4()
    processing_id = uuid4()
    unassigned_id = uuid4()
    receipt = f"RLS-UNASSIGNED-{uuid4().hex}"
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text("""
            INSERT INTO raw_payment_webhooks (
                id, merchant_request_id, checkout_request_id,
                mpesa_receipt_number, raw_payload
            ) VALUES (
                :id, :merchant_request_id, :checkout_request_id,
                :receipt, '{}'::jsonb
            )
        """), {
            "id": raw_webhook_id,
            "merchant_request_id": f"MERCHANT-{raw_webhook_id}",
            "checkout_request_id": f"CHECKOUT-{raw_webhook_id}",
            "receipt": receipt,
        })
        await connection.execute(text("""
            INSERT INTO payment_transactions (
                id, landlord_id, tenant_id, raw_webhook_id,
                merchant_request_id, checkout_request_id,
                mpesa_receipt_number, payer_phone, payer_name, amount,
                payment_method, status, completed_at
            ) VALUES (
                :id, :landlord_id, NULL, :raw_webhook_id,
                :merchant_request_id, :checkout_request_id,
                :receipt, '254711000001', 'Unmatched Payer', :amount,
                'MPESA_STK_PUSH', 'COMPLETED', CURRENT_TIMESTAMP
            )
        """), {
            "id": payment_id,
            "landlord_id": owner.landlord_id,
            "raw_webhook_id": raw_webhook_id,
            "merchant_request_id": f"MERCHANT-{raw_webhook_id}",
            "checkout_request_id": f"CHECKOUT-{raw_webhook_id}",
            "receipt": receipt,
            "amount": amount,
        })
        await connection.execute(text("""
            INSERT INTO payment_processing (
                id, mpesa_receipt_number, raw_webhook_id, landlord_id, status
            ) VALUES (:id, :receipt, :raw_webhook_id, :landlord_id, 'UNASSIGNED')
        """), {
            "id": processing_id,
            "receipt": receipt,
            "raw_webhook_id": raw_webhook_id,
            "landlord_id": owner.landlord_id,
        })
        await connection.execute(text("""
            INSERT INTO unassigned_payments (
                id, landlord_id, raw_webhook_id, mpesa_receipt_number,
                amount, payer_phone, payer_name, invalid_account_reference
            ) VALUES (
                :id, :landlord_id, :raw_webhook_id, :receipt,
                :amount, '254711000001', 'Unmatched Payer', 'INVALID-ACCOUNT'
            )
        """), {
            "id": unassigned_id,
            "landlord_id": owner.landlord_id,
            "raw_webhook_id": raw_webhook_id,
            "receipt": receipt,
            "amount": amount,
        })
    return {
        "id": unassigned_id,
        "payment_id": payment_id,
        "processing_id": processing_id,
        "raw_webhook_id": raw_webhook_id,
        "receipt": receipt,
    }


async def _delete_unassigned_fixture(rls_database, fixture: dict[str, object]) -> None:
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(
            text("DELETE FROM outbox_events WHERE aggregate_id = :payment_id"),
            {"payment_id": fixture["payment_id"]},
        )
        await connection.execute(
            text("DELETE FROM ledger_entries WHERE payment_transaction_id = :payment_id"),
            {"payment_id": fixture["payment_id"]},
        )
        await connection.execute(
            text("DELETE FROM payment_allocations WHERE payment_transaction_id = :payment_id"),
            {"payment_id": fixture["payment_id"]},
        )
        await connection.execute(
            text("DELETE FROM payment_credits WHERE payment_transaction_id = :payment_id"),
            {"payment_id": fixture["payment_id"]},
        )
        await connection.execute(
            text("DELETE FROM unassigned_payments WHERE id = :id"),
            {"id": fixture["id"]},
        )
        await connection.execute(
            text("DELETE FROM payment_processing WHERE id = :id"),
            {"id": fixture["processing_id"]},
        )
        await connection.execute(
            text("DELETE FROM payment_transactions WHERE id = :id"),
            {"id": fixture["payment_id"]},
        )
        await connection.execute(
            text("DELETE FROM raw_payment_webhooks WHERE id = :id"),
            {"id": fixture["raw_webhook_id"]},
        )


async def _resolution_client(rls_database, principal: Principal):
    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = lambda: principal
    return previous_db, previous_principal


def _restore_resolution_client(previous_db, previous_principal) -> None:
    if previous_db is None:
        api_app.dependency_overrides.pop(get_db, None)
    else:
        api_app.dependency_overrides[get_db] = previous_db
    if previous_principal is None:
        api_app.dependency_overrides.pop(get_current_principal, None)
    else:
        api_app.dependency_overrides[get_current_principal] = previous_principal


async def _assert_resolution_has_no_effects(rls_database, owner: Owner, fixture: dict[str, object], *, expected_payment_status: str = "COMPLETED") -> None:
    async with rls_database["admin_engine"].connect() as connection:
        payment = (await connection.execute(text(
            "SELECT tenant_id, status FROM payment_transactions WHERE id = :id"
        ), {"id": fixture["payment_id"]})).one()
        assert payment[0] is None
        assert payment[1] == expected_payment_status
        assert await connection.scalar(text(
            "SELECT is_paid FROM invoices WHERE id = :id"
        ), {"id": owner.invoice_id}) is False
        assert await connection.scalar(text(
            "SELECT is_resolved FROM unassigned_payments WHERE id = :id"
        ), {"id": fixture["id"]}) is False
        assert await connection.scalar(text(
            "SELECT status FROM payment_processing WHERE id = :id"
        ), {"id": fixture["processing_id"]}) == "UNASSIGNED"
        for table in ("payment_allocations", "payment_credits", "ledger_entries"):
            assert await connection.scalar(text(
                f"SELECT count(*) FROM {table} WHERE payment_transaction_id = :id"
            ), {"id": fixture["payment_id"]}) == 0
        assert await connection.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = :id"
        ), {"id": fixture["payment_id"]}) == 0


@pytest.mark.asyncio
async def test_unassigned_payment_resolution_records_all_financial_effects_and_is_idempotent(rls_database):
    owner = rls_database["a"]
    other_owner = rls_database["b"]
    fixture = await _insert_unassigned_payment(rls_database, owner)
    foreign_fixture = await _insert_unassigned_payment(rls_database, other_owner)
    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            listing = await client.get("/api/v1/unassigned-payments")
            response = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(owner.tenant_id)},
            )
            repeated = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(owner.tenant_id)},
            )
            concurrent = await asyncio.gather(*(
                client.post(
                    f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                    json={"tenant_id": str(owner.tenant_id)},
                )
                for _ in range(2)
            ))
    finally:
        _restore_resolution_client(*previous)

    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [str(fixture["id"])]
    assert set(listing.json()[0]) == {
        "id",
        "mpesa_receipt_number",
        "amount",
        "payer_phone",
        "payer_name",
        "invalid_account_reference",
        "created_at",
    }
    assert response.status_code == 200
    body = response.json()
    assert body["payment_transaction_id"] == str(fixture["payment_id"])
    assert body["tenant_id"] == str(owner.tenant_id)
    assert body["unit_id"] == str(owner.unit_id)
    assert body["allocation"]["status"] == "OVERPAYMENT_CREDITED"
    assert body["allocation"]["allocated_amount"] == "12000.00"
    assert body["allocation"]["excess_amount"] == "3000.00"
    assert repeated.status_code == 409
    assert [item.status_code for item in concurrent] == [409, 409]

    async with rls_database["admin_engine"].connect() as connection:
        assert await connection.scalar(text(
            "SELECT tenant_id FROM payment_transactions WHERE id = :id"
        ), {"id": fixture["payment_id"]}) == owner.tenant_id
        assert await connection.scalar(text(
            "SELECT status FROM payment_processing WHERE id = :id"
        ), {"id": fixture["processing_id"]}) == "COMPLETED"
        resolved = (await connection.execute(text("""
            SELECT is_resolved, resolved_unit_id, resolved_by_user_id, resolved_at
            FROM unassigned_payments WHERE id = :id
        """), {"id": fixture["id"]})).one()
        assert resolved[0] is True
        assert resolved[1] == owner.unit_id
        assert resolved[2] == UUID(owner.principal.user_id)
        assert resolved[3] is not None
        assert await connection.scalar(text(
            "SELECT count(*) FROM payment_allocations WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT amount FROM payment_credits WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 3000
        assert await connection.scalar(text(
            "SELECT count(*) FROM ledger_entries WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = :id"
        ), {"id": fixture["payment_id"]}) == 1

    await _delete_unassigned_fixture(rls_database, fixture)
    await _delete_unassigned_fixture(rls_database, foreign_fixture)


@pytest.mark.asyncio
async def test_two_landlord_users_concurrently_resolve_one_payment_once(rls_database):
    owner = rls_database["a"]
    fixture = await _insert_unassigned_payment(rls_database, owner)
    second_user_id, second_membership_id = uuid4(), uuid4()
    second_principal = Principal(
        user_id=str(second_user_id),
        role=Role.LANDLORD,
        landlord_id=str(owner.landlord_id),
    )
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text("""
            INSERT INTO app_users (id, identity_issuer, identity_subject)
            VALUES (:id, 'https://rls-test.invalid/', :subject)
        """), {"id": second_user_id, "subject": f"second-owner-{second_user_id}"})
        await connection.execute(text("""
            INSERT INTO user_memberships (id, user_id, role, landlord_id)
            VALUES (:membership_id, :user_id, 'LANDLORD', :landlord_id)
        """), {
            "membership_id": second_membership_id,
            "user_id": second_user_id,
            "landlord_id": owner.landlord_id,
        })

    active_principal: ContextVar[Principal] = ContextVar(
        "active_resolution_principal", default=owner.principal
    )

    async def override_get_db():
        async with rls_database["sessions"]() as session:
            yield session

    def override_principal() -> Principal:
        return active_principal.get()

    previous_db = api_app.dependency_overrides.get(get_db)
    previous_principal = api_app.dependency_overrides.get(get_current_principal)
    api_app.dependency_overrides[get_db] = override_get_db
    api_app.dependency_overrides[get_current_principal] = override_principal
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            async def resolve_as(principal: Principal):
                token = active_principal.set(principal)
                try:
                    return await client.post(
                        f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                        json={"tenant_id": str(owner.tenant_id)},
                    )
                finally:
                    active_principal.reset(token)

            responses = await asyncio.wait_for(
                asyncio.gather(
                    resolve_as(owner.principal),
                    resolve_as(second_principal),
                ),
                timeout=20,
            )
    finally:
        if previous_db is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_db
        if previous_principal is None:
            api_app.dependency_overrides.pop(get_current_principal, None)
        else:
            api_app.dependency_overrides[get_current_principal] = previous_principal

    assert sorted(response.status_code for response in responses) == [200, 409]
    async with rls_database["admin_engine"].connect() as connection:
        assert await connection.scalar(text(
            "SELECT is_resolved FROM unassigned_payments WHERE id = :id"
        ), {"id": fixture["id"]}) is True
        assert await connection.scalar(text(
            "SELECT COALESCE(sum(amount), 0) FROM payment_allocations WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 12000
        assert await connection.scalar(text(
            "SELECT COALESCE(sum(amount), 0) FROM payment_credits WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 3000
        assert await connection.scalar(text(
            "SELECT count(*) FROM ledger_entries WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = :id"
        ), {"id": fixture["payment_id"]}) == 1

    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text(
            "DELETE FROM user_memberships WHERE id = :id"
        ), {"id": second_membership_id})
        await connection.execute(text("DELETE FROM app_users WHERE id = :id"), {
            "id": second_user_id,
        })
    await _delete_unassigned_fixture(rls_database, fixture)


@pytest.mark.asyncio
async def test_resolution_racing_normal_allocator_preserves_one_financial_chain(rls_database):
    owner = rls_database["a"]
    fixture = await _insert_unassigned_payment(rls_database, owner)
    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            async def resolve():
                return await client.post(
                    f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                    json={"tenant_id": str(owner.tenant_id)},
                )

            async def allocate_normally():
                async with rls_database["sessions"]() as session:
                    try:
                        async with session.begin():
                            await set_rls_context(session, owner.principal)
                            return await UnassignedPaymentResolutionService(
                                session
                            ).allocation.allocate_payment(
                                payment_transaction_id=str(fixture["payment_id"]),
                                tenant_id=str(owner.tenant_id),
                                payment_amount=Decimal("15000"),
                            )
                    except AllocationConflict:
                        return {"status": "CONFLICT"}

            response, allocation_result = await asyncio.wait_for(
                asyncio.gather(resolve(), allocate_normally()),
                timeout=20,
            )
    finally:
        _restore_resolution_client(*previous)

    assert response.status_code == 200
    assert allocation_result == {"status": "CONFLICT"} or (
        allocation_result["status"] == "UNALLOCATED"
        and allocation_result["reason"] == "PAYMENT_ALREADY_CONSUMED"
    )
    async with rls_database["admin_engine"].connect() as connection:
        assert await connection.scalar(text(
            "SELECT COALESCE(sum(amount), 0) FROM payment_allocations WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 12000
        assert await connection.scalar(text(
            "SELECT COALESCE(sum(amount), 0) FROM payment_credits WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 3000
        assert await connection.scalar(text(
            "SELECT count(*) FROM ledger_entries WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
    await _delete_unassigned_fixture(rls_database, fixture)


@pytest.mark.asyncio
async def test_different_payments_resolving_same_invoice_do_not_overallocate(rls_database):
    owner = rls_database["a"]
    first = await _insert_unassigned_payment(rls_database, owner)
    second = await _insert_unassigned_payment(rls_database, owner)
    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            responses = await asyncio.wait_for(
                asyncio.gather(*(
                    client.post(
                        f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                        json={"tenant_id": str(owner.tenant_id)},
                    )
                    for fixture in (first, second)
                )),
                timeout=20,
            )
    finally:
        _restore_resolution_client(*previous)

    assert [response.status_code for response in responses] == [200, 200]
    async with rls_database["admin_engine"].connect() as connection:
        assert await connection.scalar(text(
            "SELECT COALESCE(sum(pa.amount), 0) FROM payment_allocations pa JOIN invoices i ON i.id = pa.invoice_id WHERE i.id = :id"
        ), {"id": owner.invoice_id}) == 12000
        assert await connection.scalar(text(
            "SELECT is_paid FROM invoices WHERE id = :id"
        ), {"id": owner.invoice_id}) is True
        for fixture in (first, second):
            assert await connection.scalar(text(
                "SELECT is_resolved FROM unassigned_payments WHERE id = :id"
            ), {"id": fixture["id"]}) is True
            assert await connection.scalar(text(
                "SELECT count(*) FROM ledger_entries WHERE payment_transaction_id = :id"
            ), {"id": fixture["payment_id"]}) == 1
            assert await connection.scalar(text(
                "SELECT count(*) FROM outbox_events WHERE aggregate_id = :id"
            ), {"id": fixture["payment_id"]}) == 1

    await _delete_unassigned_fixture(rls_database, first)
    await _delete_unassigned_fixture(rls_database, second)


@pytest.mark.asyncio
async def test_unassigned_resolution_rejects_foreign_and_inactive_tenants(rls_database):
    owner, other = rls_database["a"], rls_database["b"]
    fixture = await _insert_unassigned_payment(rls_database, owner)
    inactive_tenant_id = uuid4()
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text("""
            INSERT INTO tenants (
                id, landlord_id, unit_id, full_name, primary_phone,
                lease_start_date, is_active
            ) VALUES (
                :id, :landlord_id, :unit_id, 'Inactive Tenant',
                :phone, DATE '2026-01-01', FALSE
            )
        """), {
            "id": inactive_tenant_id,
            "landlord_id": owner.landlord_id,
            "unit_id": owner.unit_id,
            "phone": f"254722{inactive_tenant_id.int % 1000000:06d}",
        })

    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            foreign = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(other.tenant_id)},
            )
            inactive = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(inactive_tenant_id)},
            )
    finally:
        _restore_resolution_client(*previous)
        async with rls_database["admin_engine"].begin() as connection:
            await connection.execute(
                text("DELETE FROM tenants WHERE id = :id"),
                {"id": inactive_tenant_id},
            )
        await _delete_unassigned_fixture(rls_database, fixture)

    assert foreign.status_code == 404
    assert inactive.status_code == 404


@pytest.mark.asyncio
async def test_resolution_rejects_foreign_payment_and_forged_financial_fields(rls_database):
    owner, other = rls_database["a"], rls_database["b"]
    own_fixture = await _insert_unassigned_payment(rls_database, owner)
    foreign_fixture = await _insert_unassigned_payment(rls_database, other)
    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            foreign_payment = await client.post(
                f"/api/v1/unassigned-payments/{foreign_fixture['id']}/resolve",
                json={"tenant_id": str(other.tenant_id)},
            )
            forged_fields = await client.post(
                f"/api/v1/unassigned-payments/{own_fixture['id']}/resolve",
                json={
                    "tenant_id": str(owner.tenant_id),
                    "landlord_id": str(other.landlord_id),
                    "invoice_id": str(other.invoice_id),
                    "amount": "1.00",
                    "payment_status": "COMPLETED",
                    "allocation_status": "ALLOCATED",
                    "role": "ADMIN",
                    "ledger_amount": "1.00",
                    "outbox_event_id": str(uuid4()),
                },
            )
    finally:
        _restore_resolution_client(*previous)

    assert foreign_payment.status_code == 404
    assert forged_fields.status_code == 422
    await _assert_resolution_has_no_effects(rls_database, owner, own_fixture)
    await _assert_resolution_has_no_effects(rls_database, other, foreign_fixture)
    await _delete_unassigned_fixture(rls_database, own_fixture)
    await _delete_unassigned_fixture(rls_database, foreign_fixture)


@pytest.mark.asyncio
async def test_resolution_rejects_noncompleted_payment_without_financial_effects(rls_database):
    owner = rls_database["a"]
    fixture = await _insert_unassigned_payment(rls_database, owner)
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text(
            "UPDATE payment_transactions SET status = 'FAILED' WHERE id = :id"
        ), {"id": fixture["payment_id"]})

    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(owner.tenant_id)},
            )
    finally:
        _restore_resolution_client(*previous)

    assert response.status_code == 409
    await _assert_resolution_has_no_effects(
        rls_database, owner, fixture, expected_payment_status="FAILED"
    )
    await _delete_unassigned_fixture(rls_database, fixture)


@pytest.mark.asyncio
async def test_resolution_without_unpaid_invoice_records_full_amount_as_credit(rls_database):
    owner = rls_database["a"]
    fixture = await _insert_unassigned_payment(rls_database, owner)
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text(
            "UPDATE invoices SET is_paid = TRUE WHERE id = :id"
        ), {"id": owner.invoice_id})

    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(owner.tenant_id)},
            )
            ledger_read = await client.get(
                "/api/v1/ledger",
                params={"payment_transaction_id": str(fixture["payment_id"])},
            )
    finally:
        _restore_resolution_client(*previous)

    assert response.status_code == 200
    assert response.json()["allocation"]["status"] == "UNALLOCATED"
    assert response.json()["allocation"]["reason"] == "NO_UNPAID_INVOICE"
    assert response.json()["allocation"]["credited_amount"] == "15000.00"
    assert ledger_read.status_code == 200
    assert ledger_read.json()["total"] == 1
    assert ledger_read.json()["items"][0]["payment_transaction_id"] == str(fixture["payment_id"])
    assert ledger_read.json()["items"][0]["amount"] == "15000.00"
    async with rls_database["admin_engine"].connect() as connection:
        assert await connection.scalar(text(
            "SELECT is_paid FROM invoices WHERE id = :id"
        ), {"id": owner.invoice_id}) is True
        assert await connection.scalar(text(
            "SELECT count(*) FROM payment_allocations WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 0
        assert await connection.scalar(text(
            "SELECT count(*) FROM payment_credits WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT amount FROM payment_credits WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 15000
        assert await connection.scalar(text(
            "SELECT tenant_id FROM payment_credits WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == owner.tenant_id
        assert await connection.scalar(text(
            "SELECT count(*) FROM ledger_entries WHERE payment_transaction_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = :id"
        ), {"id": fixture["payment_id"]}) == 1
        assert await connection.scalar(text(
            "SELECT is_resolved FROM unassigned_payments WHERE id = :id"
        ), {"id": fixture["id"]}) is True
    await _delete_unassigned_fixture(rls_database, fixture)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["ledger", "outbox"])
async def test_resolution_rolls_back_all_financial_effects_after_write_failure(
    rls_database,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
):
    owner = rls_database["a"]
    fixture = await _insert_unassigned_payment(rls_database, owner)

    if failure_point == "ledger":
        original = LedgerRepository.create_credit

        async def fail_after_ledger_insert(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            raise RuntimeError("injected ledger failure after insert")

        monkeypatch.setattr(LedgerRepository, "create_credit", fail_after_ledger_insert)
    else:
        original = OutboxEventRepository.create

        async def fail_after_outbox_insert(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            raise RuntimeError("injected outbox failure after insert")

        monkeypatch.setattr(OutboxEventRepository, "create", fail_after_outbox_insert)

    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/v1/unassigned-payments/{fixture['id']}/resolve",
                json={"tenant_id": str(owner.tenant_id)},
            )
    finally:
        _restore_resolution_client(*previous)

    assert response.status_code == 500
    await _assert_resolution_has_no_effects(rls_database, owner, fixture)
    await _delete_unassigned_fixture(rls_database, fixture)


@pytest.mark.asyncio
async def test_outbox_app_access_is_limited_to_current_landlord_payment_events(rls_database):
    owner, other = rls_database["a"], rls_database["b"]
    event_id = uuid4()
    idempotency_key = f"RLS-OUTBOX-{uuid4()}"
    async with rls_database["sessions"]() as session, session.begin():
        await set_rls_context(session, owner.principal)
        await session.execute(text("""
            INSERT INTO outbox_events (
                id, event_type, aggregate_type, aggregate_id,
                idempotency_key, payload
            ) VALUES (
                :id, 'PAYMENT_PROCESSED', 'PAYMENT_TRANSACTION',
                :aggregate_id, :idempotency_key, '{}'::jsonb
            )
        """), {
            "id": event_id,
            "aggregate_id": owner.payment_id,
            "idempotency_key": idempotency_key,
        })
        assert await session.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE id = :id"
        ), {"id": event_id}) == 1

    async with rls_database["sessions"]() as session, session.begin():
        await set_rls_context(session, other.principal)
        assert await session.scalar(text(
            "SELECT count(*) FROM outbox_events WHERE id = :id"
        ), {"id": event_id}) == 0

    with pytest.raises(DBAPIError):
        async with rls_database["sessions"]() as session, session.begin():
            await set_rls_context(session, owner.principal)
            await session.execute(text("""
                INSERT INTO outbox_events (
                    event_type, aggregate_type, aggregate_id,
                    idempotency_key, payload
                ) VALUES (
                    'PAYMENT_PROCESSED', 'PAYMENT_TRANSACTION',
                    :aggregate_id, :idempotency_key, '{}'::jsonb
                )
            """), {
                "aggregate_id": other.payment_id,
                "idempotency_key": f"{idempotency_key}-foreign",
            })

    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(
            text("DELETE FROM outbox_events WHERE id = :id"),
            {"id": event_id},
        )


@pytest.mark.asyncio
async def test_payment_allocation_and_credit_reads_enforce_payment_scope(rls_database):
    owner, other = rls_database["a"], rls_database["b"]
    allocation_id = uuid4()
    credit_id = uuid4()
    async with rls_database["admin_engine"].begin() as connection:
        await connection.execute(text("""
            INSERT INTO payment_allocations (
                id, payment_transaction_id, invoice_id, amount, status
            ) VALUES (
                :id, :payment_id, :invoice_id, 4500, 'ALLOCATED'
            )
        """), {
            "id": allocation_id,
            "payment_id": owner.payment_id,
            "invoice_id": owner.invoice_id,
        })
        await connection.execute(text("""
            INSERT INTO payment_credits (
                id, payment_transaction_id, tenant_id, amount, status
            ) VALUES (
                :id, :payment_id, :tenant_id, 750, 'AVAILABLE'
            )
        """), {
            "id": credit_id,
            "payment_id": owner.payment_id,
            "tenant_id": owner.tenant_id,
        })

    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            landlord_allocations = await client.get(
                f"/api/v1/payments/{owner.payment_id}/allocations"
            )
            landlord_credits = await client.get(
                f"/api/v1/payments/{owner.payment_id}/credits"
            )
            foreign_allocations = await client.get(
                f"/api/v1/payments/{other.payment_id}/allocations"
            )
            foreign_credits = await client.get(
                f"/api/v1/payments/{other.payment_id}/credits"
            )

            tenant_principal = Principal(
                user_id=str(uuid4()),
                role=Role.TENANT,
                landlord_id=str(owner.landlord_id),
                tenant_id=str(owner.tenant_id),
            )
            await _resolution_client(rls_database, tenant_principal)
            tenant_allocations = await client.get(
                f"/api/v1/payments/{owner.payment_id}/allocations"
            )
            tenant_credits = await client.get(
                f"/api/v1/payments/{owner.payment_id}/credits"
            )
            tenant_foreign = await client.get(
                f"/api/v1/payments/{other.payment_id}/allocations"
            )
    finally:
        _restore_resolution_client(*previous)
        async with rls_database["admin_engine"].begin() as connection:
            await connection.execute(
                text("DELETE FROM payment_allocations WHERE id = :id"),
                {"id": allocation_id},
            )
            await connection.execute(
                text("DELETE FROM payment_credits WHERE id = :id"),
                {"id": credit_id},
            )

    assert landlord_allocations.status_code == 200
    assert landlord_allocations.json()[0]["id"] == str(allocation_id)
    assert landlord_allocations.json()[0]["invoice_id"] == str(owner.invoice_id)
    assert landlord_allocations.json()[0]["amount"] == "4500.00"
    assert landlord_credits.status_code == 200
    assert landlord_credits.json()[0]["id"] == str(credit_id)
    assert landlord_credits.json()[0]["tenant_id"] == str(owner.tenant_id)
    assert landlord_credits.json()[0]["amount"] == "750.00"
    assert foreign_allocations.status_code == 404
    assert foreign_credits.status_code == 404
    assert tenant_allocations.status_code == 200
    assert tenant_credits.status_code == 200
    assert tenant_foreign.status_code == 404


@pytest.mark.asyncio
async def test_ledger_read_api_lists_and_reads_only_authenticated_landlord_rows(rls_database):
    owner, other = rls_database["a"], rls_database["b"]
    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app),
            base_url="http://test",
        ) as client:
            listing = await client.get("/api/v1/ledger")
            own_entry = await client.get(f"/api/v1/ledger/{owner.ledger_id}")
            foreign_entry = await client.get(f"/api/v1/ledger/{other.ledger_id}")
    finally:
        _restore_resolution_client(*previous)

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert [row["id"] for row in listing.json()["items"]] == [str(owner.ledger_id)]
    assert own_entry.status_code == 200
    assert own_entry.json()["payment_transaction_id"] == str(owner.payment_id)
    assert own_entry.json()["amount"] == "12000.00"
    assert "payer_phone" not in own_entry.json()
    assert foreign_entry.status_code == 404


@pytest.mark.asyncio
async def test_ledger_filters_pagination_and_scope_are_deterministic(rls_database):
    owner, other = rls_database["a"], rls_database["b"]
    entry_ids = sorted([uuid4(), uuid4()])
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with rls_database["admin_engine"].begin() as connection:
        for index, entry_id in enumerate(entry_ids):
            await connection.execute(text("""
                INSERT INTO ledger_entries (
                    id, landlord_id, unit_id, tenant_id, invoice_id,
                    payment_transaction_id, mpesa_receipt_number,
                    entry_type, amount, payment_method, status, description, created_at
                ) VALUES (
                    :id, :landlord_id, :unit_id, :tenant_id, :invoice_id,
                    :payment_id, :receipt, 'CREDIT', :amount,
                    'MPESA_STK_PUSH', 'COMPLETED', 'Ledger pagination fixture', :created_at
                )
            """), {
                "id": entry_id,
                "landlord_id": owner.landlord_id,
                "unit_id": owner.unit_id,
                "tenant_id": owner.tenant_id,
                "invoice_id": owner.invoice_id,
                "payment_id": owner.payment_id,
                "receipt": f"PAGE-{entry_id}",
                "amount": 100 + index,
                "created_at": fixed_time,
            })

    previous = await _resolution_client(rls_database, owner.principal)
    try:
        async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://test") as client:
            first = await client.get("/api/v1/ledger", params={
                "created_from": fixed_time.isoformat(),
                "created_to": fixed_time.isoformat(),
                "limit": 1,
                "offset": 0,
            })
            second = await client.get("/api/v1/ledger", params={
                "created_from": fixed_time.isoformat(),
                "created_to": fixed_time.isoformat(),
                "limit": 1,
                "offset": 1,
            })
            invoice_filter = await client.get("/api/v1/ledger", params={"invoice_id": str(owner.invoice_id)})
            property_filter = await client.get(
                "/api/v1/ledger", params={"property_id": str(owner.property_id)}
            )
            receipt_filter = await client.get("/api/v1/ledger", params={"receipt": f"RLS-{owner.payment_id}"})
            empty = await client.get("/api/v1/ledger", params={"tenant_id": str(other.tenant_id)})
            forged_scope = await client.get("/api/v1/ledger", params={
                "landlord_id": str(other.landlord_id),
            })
            foreign_property_filter = await client.get(
                "/api/v1/ledger", params={"property_id": str(other.property_id)}
            )
            invalid_range = await client.get("/api/v1/ledger", params={
                "created_from": "2026-02-01T00:00:00Z",
                "created_to": "2026-01-01T00:00:00Z",
            })
            naive_date = await client.get("/api/v1/ledger", params={"created_from": "2026-01-01T00:00:00"})
    finally:
        _restore_resolution_client(*previous)

    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 2
    assert first.json()["items"][0]["id"] == str(entry_ids[1])
    assert second.json()["items"][0]["id"] == str(entry_ids[0])
    assert invoice_filter.json()["total"] == 3
    assert property_filter.json()["total"] == 3
    assert receipt_filter.json()["total"] == 1
    assert empty.json()["items"] == [] and empty.json()["total"] == 0
    assert forged_scope.status_code == 200
    assert all(row["id"] != str(other.ledger_id) for row in forged_scope.json()["items"])
    assert foreign_property_filter.status_code == 200
    assert foreign_property_filter.json()["items"] == []
    assert invalid_range.status_code == 422
    assert naive_date.status_code == 422
