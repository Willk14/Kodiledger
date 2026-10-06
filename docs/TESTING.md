# Testing KodiLedger

This guide covers the automated test suite and its optional local infrastructure. Commands use PowerShell from the repository root.

## Prerequisites

- Python 3.11 or 3.12 and the repository virtual environment with `requirements.txt` installed.
- A valid local `.env` for application settings. Do not commit `.env`.
- Docker Desktop only for tests that use local Redis or the dedicated PostgreSQL test database.

Install dependencies if needed:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run tests

Run the full suite from the repository root:

```powershell
python -m pytest -q
```

Pytest discovers tests under `app/Tests/` (`pytest.ini`). The API does not need to be started separately; HTTP integration tests use an in-process ASGI app. Tests marked `integration` may still require PostgreSQL or Redis, depending on the test.

Useful focused commands:

```powershell
# Unit and security tests
python -m pytest -q app/Tests/test_invoice_schema.py app/Tests/test_tenant_schema.py app/Tests/test_unit_schema.py app/Tests/security

# Webhook/payment PostgreSQL integration tests
python -m pytest -q app/Tests/integration/test_webhook_integration.py

# PostgreSQL RLS integration tests
python -m pytest -q app/Tests/security/test_postgres_rls.py

# Redis-backed rate limiter tests
python -m pytest -q app/Tests/integration/test_rate_limiter.py app/Tests/integration/test_stk_push_rate_limit.py
```

Some modules skip when their dedicated PostgreSQL test configuration is absent. A configured but stopped or unreachable database will fail during setup rather than be treated as a skip.

## PostgreSQL and RLS integration setup

Webhook and RLS tests use a dedicated local test cluster and the `kodiflow_test` database. Keep it separate from development and production databases: test fixtures insert and delete rows, and the initializer applies migrations and configures test roles.

1. Configure the `RLS_TEST_*` values from `.env.example` in the ignored local `.env.rls-test` file. Use a local host and port, the `kodiflow_test` database, and test-only credentials. Keep the bootstrap URL password consistent with `RLS_TEST_POSTGRES_PASSWORD`; the application and system URLs must use the dedicated `kodiflow_app` and `kodiflow_system` roles. Do not commit `.env.rls-test`.
2. Start the dedicated PostgreSQL container:

   ```powershell
   docker compose --env-file .env.rls-test -f docker-compose.rls-test.yml up -d postgres-rls-test
   ```

3. Initialize and verify the test database, roles, and migrations:

   ```powershell
   python -m app.Tests.rls_test_database
   ```

   The initializer checks that the target is the local `kodiflow_test` database and refuses several unsafe or mismatched configurations.

4. Run the PostgreSQL-backed tests:

   ```powershell
   python -m pytest -q app/Tests/security/test_postgres_rls.py app/Tests/integration/test_webhook_integration.py
   ```

5. Stop the test container when finished; this preserves its volume for the next run:

   ```powershell
   docker compose --env-file .env.rls-test -f docker-compose.rls-test.yml stop postgres-rls-test
   ```

Do not use `docker compose down -v` unless you intend to delete the dedicated test database volume and recreate its schema and roles.

## Redis-backed integration tests

The Redis rate-limit tests use `REDIS_URL` from `.env`. Start the local Redis service before running them:

```powershell
docker compose up -d redis
python -m pytest -q app/Tests/integration/test_rate_limiter.py app/Tests/integration/test_stk_push_rate_limit.py
```

The tests use unique or test-specific Redis keys and clean them up. They do not require a live M-Pesa request or a public callback tunnel.

## Troubleshooting

- **`DEBUG` setting is invalid:** set it to `true` or `false` in the process environment or local `.env`; values such as `release` are not booleans.
- **PostgreSQL connection refused:** confirm `kodiflow_rls_test_db` is running and that `RLS_TEST_PORT` agrees with the URLs in `.env.rls-test`.
- **RLS initializer rejects the target:** check that all RLS URLs point to local `kodiflow_test` on the configured port and do not alias `DATABASE_URL` or `SYSTEM_DATABASE_URL`.
- **Redis connection error:** start Redis and confirm the local `REDIS_URL` host and port.
- **Tests are skipped:** PostgreSQL-backed modules require their `.env.rls-test` configuration; inspect the pytest summary to distinguish skips from failures.

For database roles and migrations, see [DATABASE.md](DATABASE.md). For RLS and test-coverage limitations, see [SECURITY.md](SECURITY.md). The current API and workflow coverage is summarized in [API.md](API.md).
