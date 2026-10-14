# Render Staging Database Setup

This runbook prepares an **empty Render Staging Postgres database** for the KodiLedger API. It does not run automatically. Review each target before running SQL. Never use these steps against Production or a database containing data you need to keep.

The Render database should be named `kodiledger-staging-db` and be in the same Render project environment and region as the Staging API and Key Value services. The API's startup checks both `DATABASE_URL` and `SYSTEM_DATABASE_URL`; those must use distinct database logins.

## 1. Connect to the staging database as its owner

Install PostgreSQL command-line tools (`psql`) if needed. In the Render database's **Connect** menu, use the external connection details from your local computer. Do not paste a full connection URL into a command or commit it to a file. Supply the host, port, owner username, and database name as command arguments; let `psql` prompt for the owner password:

Replace the angle-bracket placeholders with the values shown by Render before running the command; do not include the password in it.

```powershell
psql -W -h <external-host> -p <port> -U <database-owner> -d <database-name>
```

At the `psql` prompt, confirm the target and whether this login can provision roles:

```sql
SELECT current_database(), current_user;
SELECT rolname, rolsuper, rolcreaterole
FROM pg_roles
WHERE rolname = current_user;
```

Confirm the database is the staging database. The migration chain creates the system role without `BYPASSRLS`; a Render database owner does not need superuser or `BYPASSRLS` privileges. The owner must be able to create ordinary login roles. If role creation or a migration fails, stop and resolve the error before proceeding. Do not substitute the database owner login for either application connection.

## 2. Create the application login

The application role must not bypass row-level security. Create it before migrations because migration 0011 revokes privileges from it. Migration 0011 creates `kodiflow_system` as a non-bypass role; migration 0019 grants it explicit access policies on the current RLS-protected tables used by trusted callbacks and workers. Those policies allow all rows on the named tables, so the system credential remains high-trust. Future RLS tables do not receive system access automatically.

Run the following in the same owner `psql` session:

```sql
CREATE ROLE kodiflow_app
  WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
\password kodiflow_app
```

At the `\password` prompt, enter a unique, strong password. `psql` prompts twice; the password is not included in the SQL command or shell history. Store it securely so you can construct the Render environment value later. Never put it in source control, screenshots, or chat.

`kodiflow_app` is not a Render-managed credential. You will rotate its password with PostgreSQL and update the corresponding Render service variable yourself. `kodiflow_system` is created by migration 0011; set its password after migrations with `\password kodiflow_system`. Neither application role is the Render-managed database-owner credential.

If `kodiflow_app` already exists, do not rerun `CREATE ROLE`. Inspect its attributes first and use `ALTER ROLE` to set the exact attributes above, then use `\password kodiflow_app` to set its password. Do not grant `BYPASSRLS` to either role.

## 3. Apply the schema migrations

Exit the SQL prompt (`\q`) and, from the backend repository root, apply every numbered file in `db/migrations/` in lexicographic order, from `0001_initial_schema.sql` through `0020_invoice_stk_push.sql`, using the owner connection. The repository has no migration runner or migration-history table. Use `psql` with `ON_ERROR_STOP` and stop at the first error; do not skip a failed migration or rerun the whole sequence over a partially migrated database.

Example for one migration (repeat for each file in order, entering the owner password only at the prompt):

```powershell
psql -W -v ON_ERROR_STOP=1 -h <external-host> -p <port> -U <database-owner> -d <database-name> -f .\db\migrations\0001_initial_schema.sql
```

The complete ordered migration list is:

```text
0001_initial_schema.sql
0002_payment_processing.sql
0003_add_payment_processing_processed_at.sql
0004_payment_transactions.sql
0005_payment_allocations.sql
0006_link_ledger_to_payment_transaction.sql
0007_payment_credits.sql
0008_add_financial_query_indexes.sql
0009_outbox_events.sql
0010_row_level_security.sql
0011_rls_role_hardening.sql
0012_outbox_claiming.sql
0013_authenticated_identity.sql
0014_webhook_inbox_retries.sql
0015_stk_status_queries.sql
0016_scoped_outbox_app_access.sql
0017_payment_credit_applications.sql
0018_identity_lookup_rls.sql
0019_system_role_rls_policies.sql
0020_invoice_stk_push.sql
```

## 4. Apply the application-role grants

After all migrations succeed, connect again as the database owner, set the generated system-role password with `\password kodiflow_system`, then run these grants. They follow the repository's RLS test bootstrap: business-table CRUD under RLS, identity mappings read-only, no raw webhook access, and only scoped `SELECT`/`INSERT` access to the outbox.

```sql
GRANT CONNECT ON DATABASE <database-name> TO kodiflow_app;
GRANT USAGE ON SCHEMA public, app TO kodiflow_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kodiflow_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kodiflow_app;
REVOKE INSERT, UPDATE, DELETE ON app_users, user_memberships FROM kodiflow_app;
REVOKE ALL ON raw_payment_webhooks, outbox_events FROM kodiflow_app;
GRANT SELECT, INSERT ON outbox_events TO kodiflow_app;
```

Replace `<database-name>` with the actual database identifier (not the Render service name). If any table or role is missing, or any grant fails, stop and investigate rather than broadening privileges.

## 5. Verify role separation

Still as the owner, verify the role attributes:

```sql
SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolbypassrls
FROM pg_roles
WHERE rolname IN ('kodiflow_app', 'kodiflow_system')
ORDER BY rolname;
```

Expected: both roles can log in; neither is a superuser, role creator, or RLS-bypass role (`rolbypassrls = false`). Confirm that `kodiflow_system` has the explicit `kodiflow_system_access` policy on every RLS-protected table required by the migration. Also verify that all 19 migration files completed without errors. This is setup verification only; it is not a test of API authorization or RLS isolation.

## 6. Configure the Render API variables

Only after the database setup succeeds, set the API service variables in the **Staging** environment. Build two distinct connection URLs using the Render **internal** database host, database name, port, and the passwords above:

- `DATABASE_URL`: username `kodiflow_app`, scheme `postgresql+asyncpg://`.
- `SYSTEM_DATABASE_URL`: username `kodiflow_system`, scheme `postgresql+asyncpg://`.

Both URLs point to the same staging database, but must have different usernames and passwords. Percent-encode reserved characters in either password when placing it in a URL. Do not use the database owner's credentials for either URL. Add the Render Key Value internal URL as `REDIS_URL`.

Other required settings are `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`, `MPESA_SHORTCODE`, and `MPESA_CALLBACK_URL`. Use only staging values and Safaricom Daraja sandbox credentials. `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are legacy/local Docker Compose settings; the hosted API does not use them to connect, so do not put the Render database-owner password in the API service. Before enabling payment callbacks outside development/test, configure `MPESA_CALLBACK_TOKEN` as a random value of at least 32 characters and set `MPESA_CALLBACK_URL` to the public HTTPS URL for `POST /api/v1/webhooks/mpesa` **without** a token query parameter; the backend appends the configured token. Configure `ENVIRONMENT=staging`, `DEBUG=false`, and the exact staging frontend origin in `CORS_ALLOWED_ORIGINS`. If the frontend is also hosted on Render, use its Render HTTPS origin. Configure the OIDC issuer, audience, and JWKS URL for the identity provider before expecting authenticated API calls to succeed.

## 7. Create the API Web Service

Create a **Web Service** from the backend Git repository and select the **Staging** project environment. The repository root contains `requirements.txt` and `app/main.py`, so leave Root Directory blank. Use:

| Setting | Value |
| --- | --- |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/` |

Add the service variables from the prior section before deployment. Verify that the two database URLs use the **internal** Render Postgres host, the app and system role credentials respectively, and the same Staging database. Use the internal Render Key Value URL for `REDIS_URL`. Never paste complete URLs or passwords into chat, source control, or deployment logs. The app checks both PostgreSQL connections during startup; an incorrect URL prevents the service from becoming ready.

The API alone does not drain the transactional outbox. The worker in `app/workers/outbox.py` must run as a separate Background Worker with the database URLs and other required settings configured, plus a reachable Kafka broker configured through `KAFKA_BOOTSTRAP_SERVERS`. Do not treat payment event delivery as staged until that broker and worker are deployed and verified. The repository currently does not provision a hosted Kafka broker.

After the web service deploys, verify the Render logs and open its HTTPS URL. `GET /` should return the basic online response; successful startup also confirms the two database connections succeeded. This does not verify RLS isolation, authenticated routes, M-Pesa callbacks, or outbox publication.

Do not deploy until every required setting has a real staging value. A Render deployment, migration, role setup, or connectivity check does not by itself validate application authorization or RLS isolation.
