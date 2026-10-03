from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
import app.security.authentication as authentication
from app.security.dependencies import get_current_principal
from app.security.principals import Principal
from app.security.rls import get_rls_db, set_rls_context
from app.security.roles import Role
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
                                            payment_transaction_id, entry_type, amount,
                                            payment_method, status, description)
                VALUES (:id, :landlord_id, :unit_id, :tenant_id, :invoice_id, :payment_id,
                        'CREDIT', 12000, 'MPESA_STK_PUSH', 'COMPLETED', 'RLS integration fixture')
            """), {"id": owner.ledger_id, "landlord_id": owner.landlord_id, "unit_id": owner.unit_id,
                  "tenant_id": owner.tenant_id, "invoice_id": owner.invoice_id, "payment_id": owner.payment_id})

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
    finally:
        if previous_override is None:
            api_app.dependency_overrides.pop(get_db, None)
        else:
            api_app.dependency_overrides[get_db] = previous_override

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(owner.user_id)
    assert body["role"] == "LANDLORD"
    assert body["landlord_id"] == str(owner.landlord_id)
    # Each landlord has one fixture property; without RLS the count would be two.
    assert body["property_count"] == 1


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
                       (SELECT count(*) FROM invoices)
            """))).one()
        assert row[0] == "kodiflow_system"
        assert row[1] is True
        assert row[2] == 2
    finally:
        await engine.dispose()
