"""Safely initialize the dedicated disposable PostgreSQL RLS test database."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import unquote

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env.rls-test"
MIGRATIONS = ROOT / "db" / "migrations"
EXPECTED_DATABASE = "kodiflow_test"
EXPECTED_APP_ROLE = "kodiflow_app"
EXPECTED_SYSTEM_ROLE = "kodiflow_system"
RLS_TABLES = (
    "landlords",
    "properties",
    "units",
    "tenants",
    "invoices",
    "ledger_entries",
    "payment_processing",
    "payment_transactions",
    "payment_allocations",
    "payment_credits",
    "payment_credit_applications",
    "unassigned_payments",
    "outbox_events",
    "utility_readings",
    "user_device_tokens",
)


def _config() -> dict[str, str]:
    values = {key: value for key, value in dotenv_values(ENV_FILE).items() if value}
    required = (
        "RLS_TEST_ADMIN_BOOTSTRAP_DATABASE_URL",
        "RLS_TEST_ADMIN_DATABASE_URL",
        "RLS_TEST_DATABASE_URL",
        "RLS_TEST_SYSTEM_DATABASE_URL",
    )
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise RuntimeError(f"Missing RLS test settings in {ENV_FILE.name}: {', '.join(missing)}")
    return values  # type: ignore[return-value]


def _asyncpg_connect_args(url: str) -> dict[str, object]:
    parsed = make_url(url)
    return {
        "host": parsed.host,
        "port": parsed.port,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.database,
        "timeout": 5,
    }


def _target(url: str) -> tuple[str | None, int | None, str | None]:
    parsed = make_url(url)
    return parsed.host, parsed.port, parsed.database


def _assert_safe_configuration(config: dict[str, str]) -> None:
    admin = make_url(config["RLS_TEST_ADMIN_DATABASE_URL"])
    bootstrap = make_url(config["RLS_TEST_ADMIN_BOOTSTRAP_DATABASE_URL"])
    app = make_url(config["RLS_TEST_DATABASE_URL"])
    system = make_url(config["RLS_TEST_SYSTEM_DATABASE_URL"])

    if admin.database != EXPECTED_DATABASE or app.database != EXPECTED_DATABASE or system.database != EXPECTED_DATABASE:
        raise RuntimeError(f"RLS tests may only target the explicitly named {EXPECTED_DATABASE} database.")
    if admin.username != "postgres" or bootstrap.username != "postgres":
        raise RuntimeError("RLS test migration/bootstrap connections must use the isolated test cluster's postgres role.")
    if app.username != EXPECTED_APP_ROLE or system.username != EXPECTED_SYSTEM_ROLE:
        raise RuntimeError("RLS test application/system URLs must use their dedicated database roles.")
    if _target(admin) != _target(app) or _target(admin) != _target(system):
        raise RuntimeError("RLS test URLs do not point to the same dedicated test database.")
    if _target(bootstrap)[:2] != _target(admin)[:2] or bootstrap.database != "kodiflow_db":
        raise RuntimeError("Bootstrap URL must target kodiflow_db in the isolated RLS test cluster.")
    if admin.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("RLS test database must be a local disposable PostgreSQL instance.")
    if admin.port != int(config.get("RLS_TEST_PORT", "5435")):
        raise RuntimeError("RLS test database port does not match RLS_TEST_PORT.")

    # Protect against accidentally aliasing either configured application DB.
    from app.core.config import settings

    target = _target(admin)
    for configured in (settings.DATABASE_URL, settings.SYSTEM_DATABASE_URL):
        if target == _target(configured):
            raise RuntimeError("RLS test database aliases a configured application/system database.")


async def _connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(**_asyncpg_connect_args(url))


async def _verify_cluster_admin(
    connection: asyncpg.Connection,
    expected_database: str = "kodiflow_db",
) -> None:
    row = await connection.fetchrow(
        "SELECT current_database() AS db, r.rolsuper AS is_superuser "
        "FROM pg_roles r WHERE r.rolname = current_user"
    )
    if not row or row["db"] != expected_database or not row["is_superuser"]:
        raise RuntimeError("Refusing database initialization: bootstrap is not postgres on the isolated cluster.")


async def _role_exists(connection: asyncpg.Connection, role: str) -> bool:
    return bool(await connection.fetchval("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = $1)", role))


async def _set_role_password(connection: asyncpg.Connection, role: str, password: str) -> None:
    quoted = await connection.fetchval("SELECT quote_literal($1)", password)
    await connection.execute(f"ALTER ROLE {role} WITH LOGIN PASSWORD {quoted}")


async def _create_test_database_if_missing(config: dict[str, str]) -> None:
    connection = await _connect(config["RLS_TEST_ADMIN_BOOTSTRAP_DATABASE_URL"])
    try:
        await _verify_cluster_admin(connection)
        exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)", EXPECTED_DATABASE
        )
        if not exists:
            await connection.execute(f"CREATE DATABASE {EXPECTED_DATABASE} TEMPLATE template0 ENCODING 'UTF8'")
    finally:
        await connection.close()


async def _ensure_app_role(connection: asyncpg.Connection, config: dict[str, str]) -> None:
    app_url = make_url(config["RLS_TEST_DATABASE_URL"])
    if not app_url.password:
        raise RuntimeError("RLS test application URL must contain its local test password.")
    if not await _role_exists(connection, EXPECTED_APP_ROLE):
        quoted = await connection.fetchval("SELECT quote_literal($1)", unquote(app_url.password))
        await connection.execute(
            f"CREATE ROLE {EXPECTED_APP_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOBYPASSRLS PASSWORD {quoted}"
        )
    else:
        await _set_role_password(connection, EXPECTED_APP_ROLE, unquote(app_url.password))


async def _apply_migrations(connection: asyncpg.Connection) -> None:
    existing = await connection.fetchval("SELECT to_regclass('public.landlords')")
    if existing:
        identity_exists = await connection.fetchval("SELECT to_regclass('public.app_users')")
        if not identity_exists:
            raise RuntimeError("Test database has a partial schema; refusing to apply migrations over it.")
        webhook_retry_columns = await connection.fetchval("""
            SELECT count(*) = 4
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'raw_payment_webhooks'
              AND column_name = ANY(ARRAY[
                  'attempt_count', 'next_attempt_at', 'locked_at', 'retry_exhausted_at'
              ])
        """)
        if not webhook_retry_columns:
            await connection.execute(
                (MIGRATIONS / "0014_webhook_inbox_retries.sql").read_text(encoding="utf-8")
            )
        stk_requests_exist = await connection.fetchval(
            "SELECT to_regclass('public.stk_push_requests')"
        )
        if not stk_requests_exist:
            await connection.execute(
                (MIGRATIONS / "0015_stk_status_queries.sql").read_text(encoding="utf-8")
            )
        outbox_policy_exists = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = 'public.outbox_events'::regclass "
            "AND polname = 'outbox_payment_scope_select')"
        )
        if not outbox_policy_exists:
            await connection.execute(
                (MIGRATIONS / "0016_scoped_outbox_app_access.sql").read_text(encoding="utf-8")
            )
        credit_applications_exist = await connection.fetchval(
            "SELECT to_regclass('public.payment_credit_applications')"
        )
        if not credit_applications_exist:
            await connection.execute(
                (MIGRATIONS / "0017_payment_credit_applications.sql").read_text(encoding="utf-8")
            )
        identity_lookup_policy_exists = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = 'public.app_users'::regclass "
            "AND polname = 'app_users_kodiflow_app_read')"
        )
        if not identity_lookup_policy_exists:
            await connection.execute(
                (MIGRATIONS / "0018_identity_lookup_rls.sql").read_text(encoding="utf-8")
            )
        return

    for migration in sorted(MIGRATIONS.glob("*.sql")):
        await connection.execute(migration.read_text(encoding="utf-8"))


async def _grant_app_runtime_privileges(connection: asyncpg.Connection) -> None:
    # Mirrors ordinary application CRUD access for business tables. Identity
    # mappings stay read-only, while system-only integration tables stay denied.
    await connection.execute("GRANT CONNECT ON DATABASE kodiflow_test TO kodiflow_app")
    await connection.execute("GRANT USAGE ON SCHEMA public, app TO kodiflow_app")
    await connection.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kodiflow_app"
    )
    await connection.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kodiflow_app")
    await connection.execute("REVOKE INSERT, UPDATE, DELETE ON app_users, user_memberships FROM kodiflow_app")
    await connection.execute("REVOKE ALL ON raw_payment_webhooks, outbox_events FROM kodiflow_app")
    await connection.execute("GRANT SELECT, INSERT ON outbox_events TO kodiflow_app")
    await connection.execute("GRANT CONNECT ON DATABASE kodiflow_test TO kodiflow_system")


async def _verify_schema_and_roles(connection: asyncpg.Connection) -> None:
    if await connection.fetchval("SELECT current_database()") != EXPECTED_DATABASE:
        raise RuntimeError("Schema verification connected to an unexpected database.")

    roles = await connection.fetch(
        "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles "
        "WHERE rolname = ANY($1::text[])",
        [EXPECTED_APP_ROLE, EXPECTED_SYSTEM_ROLE],
    )
    by_name = {row["rolname"]: row for row in roles}
    app, system = by_name.get(EXPECTED_APP_ROLE), by_name.get(EXPECTED_SYSTEM_ROLE)
    if not app or app["rolsuper"] or app["rolbypassrls"] or not app["rolcanlogin"]:
        raise RuntimeError("kodiflow_app is missing or has unsafe elevated/RLS-bypass attributes.")
    if not system or system["rolsuper"] or not system["rolbypassrls"] or not system["rolcanlogin"]:
        raise RuntimeError("kodiflow_system is missing its separate expected BYPASSRLS role attributes.")

    relations = await connection.fetch(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
        "EXISTS(SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = ANY($1::text[])",
        list(RLS_TABLES),
    )
    by_table = {row["relname"]: row for row in relations}
    missing = sorted(set(RLS_TABLES) - by_table.keys())
    if missing:
        raise RuntimeError(f"Migration chain did not create expected RLS tables: {', '.join(missing)}")
    for name in RLS_TABLES:
        row = by_table[name]
        if not row["relrowsecurity"] or not row["relforcerowsecurity"] or not row["has_policy"]:
            raise RuntimeError(f"RLS/forced RLS policy verification failed for {name}.")

    identity_constraints = await connection.fetch(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'public.user_memberships'::regclass"
    )
    names = {row["conname"] for row in identity_constraints}
    required = {
        "ck_user_memberships_application_role",
        "ck_user_memberships_role_scope",
        "fk_user_memberships_tenant_landlord",
    }
    if not required.issubset(names):
        raise RuntimeError("Migration 0013 identity membership constraints are incomplete.")
    if not await connection.fetchval("SELECT to_regclass('public.app_users')"):
        raise RuntimeError("Migration 0013 did not create app_users.")


async def initialize() -> None:
    config = _config()
    _assert_safe_configuration(config)
    await _create_test_database_if_missing(config)

    bootstrap = await _connect(config["RLS_TEST_ADMIN_DATABASE_URL"])
    try:
        await _verify_cluster_admin(bootstrap, EXPECTED_DATABASE)
        await _ensure_app_role(bootstrap, config)
        await _apply_migrations(bootstrap)
        system_url = make_url(config["RLS_TEST_SYSTEM_DATABASE_URL"])
        if not system_url.password:
            raise RuntimeError("RLS test system URL must contain its local test password.")
        await _set_role_password(bootstrap, EXPECTED_SYSTEM_ROLE, unquote(system_url.password))
        await _grant_app_runtime_privileges(bootstrap)
        await _verify_schema_and_roles(bootstrap)
    finally:
        await bootstrap.close()


if __name__ == "__main__":
    asyncio.run(initialize())
