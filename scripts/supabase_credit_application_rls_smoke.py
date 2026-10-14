"""Exercise payment-credit-application RLS on the KodiLedger dev Supabase DB.

The system connection seeds isolated synthetic rows and removes them in a
finally block. The application connection verifies read and insert policies.
No connection strings or passwords are printed.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from uuid import uuid4

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HOST = "aws-0-eu-west-1.pooler.supabase.com"
EXPECTED_PROJECT = "zdimjphpmbekgaxsmpvu"


def _connection_parts(name: str, expected_role: str) -> dict[str, object]:
    values = dotenv_values(ROOT / ".env")
    raw_url = values.get(name)
    if not raw_url:
        raise RuntimeError(f"{name} is missing from .env")

    url = make_url(raw_url)
    expected_user = f"{expected_role}.{EXPECTED_PROJECT}"
    if (
        url.host != EXPECTED_HOST
        or url.database != "postgres"
        or url.username != expected_user
        or not url.password
    ):
        raise RuntimeError(f"{name} does not target the expected KodiLedger-dev {expected_role} login")

    return {
        "host": url.host,
        "port": url.port or 5432,
        "database": url.database,
        "user": url.username,
        "password": url.password,
        "ssl": "require",
        "timeout": 15,
    }


async def _seed(system: asyncpg.Connection, fixtures: dict[str, object]) -> None:
    a = fixtures["a"]
    b = fixtures["b"]
    async with system.transaction():
        await system.executemany(
            """INSERT INTO landlords (id, full_name, email, phone_number)
               VALUES ($1, $2, $3, $4)""",
            [
                (a["landlord"], "RLS Smoke A", f"rls-a-{a['suffix']}@example.invalid", f"254700{a['suffix'][:9]}"),
                (b["landlord"], "RLS Smoke B", f"rls-b-{b['suffix']}@example.invalid", f"254700{b['suffix'][:9]}"),
            ],
        )
        await system.executemany(
            """INSERT INTO properties (id, landlord_id, name, county, total_units)
               VALUES ($1, $2, $3, 'Test', 1)""",
            [(owner["property"], owner["landlord"], f"RLS {owner['name']}") for owner in (a, b)],
        )
        await system.executemany(
            """INSERT INTO units (id, property_id, landlord_id, unit_number, base_rent)
               VALUES ($1, $2, $3, $4, 1000)""",
            [(owner["unit"], owner["property"], owner["landlord"], f"RLS-{owner['name']}") for owner in (a, b)],
        )
        await system.executemany(
            """INSERT INTO tenants (id, landlord_id, unit_id, full_name, primary_phone, lease_start_date)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            [
                (a["tenant"], a["landlord"], a["unit"], "RLS Tenant A", f"254711{a['suffix'][:9]}", date(2026, 10, 1)),
                (b["tenant"], b["landlord"], b["unit"], "RLS Tenant B", f"254711{b['suffix'][:9]}", date(2026, 10, 1)),
            ],
        )
        await system.executemany(
            """INSERT INTO invoices
                 (id, landlord_id, unit_id, tenant_id, invoice_number, billing_month, rent_amount, due_date)
               VALUES ($1, $2, $3, $4, $5, $6, 1000, $7)""",
            [
                (owner["invoice"], owner["landlord"], owner["unit"], owner["tenant"],
                 f"RLS-{owner['name']}-{owner['suffix']}", date(2026, 10, 1), date(2026, 10, 31))
                for owner in (a, b)
            ],
        )
        await system.executemany(
            """INSERT INTO payment_transactions
                 (id, landlord_id, tenant_id, mpesa_receipt_number, amount, payment_method, status)
               VALUES ($1, $2, $3, $4, 200, 'MPESA_STK_PUSH', 'COMPLETED')""",
            [
                (owner["payment"], owner["landlord"], owner["tenant"],
                 f"RLS-RECEIPT-{owner['name']}-{owner['suffix']}")
                for owner in (a, b)
            ],
        )
        await system.executemany(
            """INSERT INTO payment_credits (id, payment_transaction_id, tenant_id, amount)
               VALUES ($1, $2, $3, 100)""",
            [
                (owner["credit_read"], owner["payment"], owner["tenant"])
                for owner in (a, b)
            ] + [
                (owner["credit_insert"], owner["payment"], owner["tenant"])
                for owner in (a, b)
            ],
        )
        await system.executemany(
            """INSERT INTO payment_credit_applications
                 (id, payment_credit_id, invoice_id, amount, application_key)
               VALUES ($1, $2, $3, 25, $4)""",
            [
                (owner["application"], owner["credit_read"], owner["invoice"],
                 f"rls-smoke-seed-{owner['name']}-{owner['suffix']}")
                for owner in (a, b)
            ],
        )


async def _verify(app: asyncpg.Connection, fixtures: dict[str, object]) -> None:
    a = fixtures["a"]
    b = fixtures["b"]
    allowed_application = uuid4()
    async with app.transaction():
        current_user = await app.fetchval("SELECT current_user")
        if current_user != "kodiflow_app":
            raise RuntimeError("Application connection did not authenticate as kodiflow_app")

        for owner, other in ((a, b), (b, a)):
            await app.fetchval(
                "SELECT set_config('app.current_landlord_id', $1, true)",
                str(owner["landlord"]),
            )
            visible = await app.fetch(
                """SELECT id FROM payment_credit_applications
                   WHERE id = ANY($1::uuid[]) ORDER BY id""",
                [owner["application"], other["application"]],
            )
            if {row["id"] for row in visible} != {owner["application"]}:
                raise AssertionError(f"{owner['name']} did not see exactly its own application")

        await app.fetchval("SELECT set_config('app.current_landlord_id', $1, true)", str(a["landlord"]))
        await app.execute(
            """INSERT INTO payment_credit_applications
                 (id, payment_credit_id, invoice_id, amount, application_key)
               VALUES ($1, $2, $3, 10, $4)""",
            allowed_application,
            a["credit_insert"],
            a["invoice"],
            f"rls-smoke-allowed-{a['suffix']}",
        )

        denied = False
        try:
            async with app.transaction():
                await app.execute(
                    """INSERT INTO payment_credit_applications
                         (id, payment_credit_id, invoice_id, amount, application_key)
                       VALUES ($1, $2, $3, 10, $4)""",
                    uuid4(),
                    b["credit_insert"],
                    b["invoice"],
                    f"rls-smoke-denied-{a['suffix']}",
                )
        except asyncpg.InsufficientPrivilegeError:
            denied = True
        if not denied:
            raise AssertionError("Cross-landlord application insert unexpectedly succeeded")

        visible_after_insert = await app.fetch(
            "SELECT id FROM payment_credit_applications WHERE id = ANY($1::uuid[])",
            [a["application"], b["application"], allowed_application],
        )
        if {row["id"] for row in visible_after_insert} != {a["application"], allowed_application}:
            raise AssertionError("Post-insert RLS visibility was incorrect")


async def _cleanup(system: asyncpg.Connection, fixtures: dict[str, object]) -> None:
    a = fixtures["a"]
    b = fixtures["b"]
    owners = (a, b)
    async with system.transaction():
        await system.execute(
            "DELETE FROM payment_credit_applications WHERE payment_credit_id = ANY($1::uuid[])",
            [owner[key] for owner in owners for key in ("credit_read", "credit_insert")],
        )
        await system.execute(
            "DELETE FROM payment_credits WHERE id = ANY($1::uuid[])",
            [owner[key] for owner in owners for key in ("credit_read", "credit_insert")],
        )
        await system.execute(
            "DELETE FROM payment_transactions WHERE id = ANY($1::uuid[])",
            [owner["payment"] for owner in owners],
        )
        await system.execute(
            "DELETE FROM invoices WHERE id = ANY($1::uuid[])",
            [owner["invoice"] for owner in owners],
        )
        await system.execute(
            "DELETE FROM tenants WHERE id = ANY($1::uuid[])",
            [owner["tenant"] for owner in owners],
        )
        await system.execute(
            "DELETE FROM units WHERE id = ANY($1::uuid[])",
            [owner["unit"] for owner in owners],
        )
        await system.execute(
            "DELETE FROM properties WHERE id = ANY($1::uuid[])",
            [owner["property"] for owner in owners],
        )
        await system.execute(
            "DELETE FROM landlords WHERE id = ANY($1::uuid[])",
            [owner["landlord"] for owner in owners],
        )


async def main() -> None:
    app_options = _connection_parts("DATABASE_URL", "kodiflow_app")
    system_options = _connection_parts("SYSTEM_DATABASE_URL", "kodiflow_system")

    fixtures: dict[str, object] = {}
    for name in ("a", "b"):
        suffix = uuid4().hex[:12]
        fixtures[name] = {
            "name": name.upper(),
            "suffix": suffix,
            "landlord": uuid4(),
            "property": uuid4(),
            "unit": uuid4(),
            "tenant": uuid4(),
            "invoice": uuid4(),
            "payment": uuid4(),
            "credit_read": uuid4(),
            "credit_insert": uuid4(),
            "application": uuid4(),
        }

    system = await asyncpg.connect(**system_options)
    try:
        await _seed(system, fixtures)
        app = await asyncpg.connect(**app_options)
        try:
            await _verify(app, fixtures)
        finally:
            await app.close()
    finally:
        try:
            await _cleanup(system, fixtures)
        finally:
            await system.close()

    print("PASS: Supabase kodiflow_app enforced credit-application RLS; synthetic fixtures cleaned up.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Do not print connection URLs, usernames, or password-bearing errors.
        print(f"FAIL: Supabase RLS smoke check stopped ({type(exc).__name__}); cleanup was attempted.")
        raise SystemExit(1) from None
