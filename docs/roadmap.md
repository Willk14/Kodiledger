# M-Pesa STK Push Sandbox Callback Roadmap

## API contract stabilization before Supabase

Status: **Complete for the currently implemented API surface and regression-verified** (2026-10-06). This is a stability checkpoint for database integration, not a permanent freeze; planned workflows remain open for future design.

- Audited registered FastAPI routes against `docs/API.md` and the generated OpenAPI schema. The caretaker context route was missing its endpoint-level contract and is now documented.
- Added an OpenAPI route-manifest test that makes additions/removals/method changes explicit, including the absence of a generic `/api/v1/allocations` endpoint.
- The PostgreSQL race test exposed a repeatable deadlock when separate successful payments for one tenant simultaneously upgraded foreign-key key-share locks to a stronger tenant lock. The tenant serialization now uses `FOR NO KEY UPDATE`, preserving mutual exclusion while avoiding that upgrade conflict. The focused race test passes.
- Contract baseline: current routes, request/response schemas, auth boundaries, and financial behaviors remain unchanged during the first Supabase database integration. Any required API change must update OpenAPI checks and synchronized docs deliberately.
- The Supabase development-project migration and connection rehearsal was completed on 2026-10-06. Initial role and RLS validation completed on 2026-10-07 using read-only Supabase catalog checks, local PostgreSQL tests, and a guarded behavior smoke check against the actual Supabase application role. No application data has been moved. Keep OIDC and API behavior unchanged during this database-only integration.
- Decision 8 records the trade-offs and guardrails in `docs/decisions.md`.

### Supabase development database preparation

- Managed PostgreSQL compatibility update (2026-10-09): migration 0011 creates the system role without BYPASSRLS, and migration 0019 replaces the role-level bypass with explicit system policies on enumerated RLS tables. This supports managed PostgreSQL services where the database owner cannot grant BYPASSRLS; the system credential remains high-trust and can access all rows on the listed tables.

- **Compatibility issue found and fixed:** migration `0011_rls_role_hardening.sql` granted `CONNECT` to a hard-coded local database name (`kodiflow_db`). It now grants access to `current_database()`, which supports Supabase's project database name without changing role scope.
- Migrations are manual SQL files; this repository has no migration runner/history table. Apply `db/migrations/*.sql` in numeric order to a new, empty development project, using a privileged project connection only for schema changes.
- Provision a separate SQL login role `kodiflow_app` before migrations that grant/revoke its privileges. Migration 0011 creates `kodiflow_system`; both roles must have `NOBYPASSRLS`. Migration 0019 supplies explicit system-only policies on the reviewed tables needed by trusted webhook/worker workflows. Set each password separately in a secure prompt/secret store. Never use a Supabase API `service_role` key as a PostgreSQL connection string.
- Migration `0011` creates `kodiflow_system` without a password, and the migration set does not create `kodiflow_app`; this provisioning gap must be handled before applying the SQL. Confirm that the Supabase project database owner can create/configure the required custom roles before migration rehearsal.
- Supabase projects include Data API roles and grants in addition to PostgreSQL login roles. Before enabling any Data API access, inspect grants and default privileges for `anon`, `authenticated`, and `service_role`; KodiLedger currently expects all business access through FastAPI and does not use Supabase Data API.
- Select a database connection mode from the backend host's IP support: direct for persistent service hosts with IPv6, or Supabase session pooler for IPv4-only hosts. Use TLS and verify pooler compatibility before setting production connection-pool options.
- After role setup, apply the migration chain on the empty dev project, verify database name, migration results, role attributes, table grants, RLS/`FORCE RLS`, and cross-landlord policies, then run the PostgreSQL security/integration suite against that project before moving any data.
- **Development rehearsal completed (2026-10-06):** created the `KodiLedger-dev` Supabase project and applied `db/migrations/0001` through `0017` in numeric order using the SQL Editor. Created `kodiflow_app` as a login role with `NOBYPASSRLS`; migration `0011` created `kodiflow_system` with its intended `BYPASSRLS` capability. Applied the least-privilege table grants and restrictions from the RLS test setup. No application data was moved.
- **Connection mode:** used the shared Session pooler on port `5432` for the local IPv4 development environment. Pooler logins use the role and project reference as the username. Both role passwords were set privately through `psql`'s `\\password` command; never put them in docs, screenshots, SQL Editor queries, or chat.
- **Async SQLAlchemy TLS setting:** use `?ssl=require` on `postgresql+asyncpg` URLs. The `sslmode=require` option is passed as an unsupported keyword by SQLAlchemy's asyncpg dialect and fails with `connect() got an unexpected keyword argument 'sslmode'`. See [asyncpg connection options](https://magicstack.github.io/asyncpg/current/api/index.html) and [SQLAlchemy's asyncpg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#connect-string).
- **Connection verification completed (2026-10-06):** `kodiflow_app` authenticated through the Session pooler and returned `current_user = kodiflow_app`, `current_database = postgres`. After correcting the asyncpg SSL URL option and matching the rotated app-role password in the ignored local `.env`, Uvicorn reported `Application startup complete`; its lifespan executes `SELECT 1` through both application and system engines. This confirms connectivity only.
- **Role verification completed (2026-10-06):** Supabase reports `kodiflow_app` as login-capable, non-superuser, and `NOBYPASSRLS`; `kodiflow_system` as login-capable, non-superuser, and `BYPASSRLS`. This matches the intended role separation.
- **RLS policy catalog verification completed (2026-10-07):** the read-only `pg_policies` query returned 58 policies. `payment_credit_applications` has the four expected policies: landlord/tenant-scoped `SELECT` and `INSERT`, with `UPDATE` and `DELETE` denied.
- **Payment credit application RLS behavior verified (2026-10-07):** the local PostgreSQL RLS test now checks that each landlord sees only its own application, a valid same-landlord insert succeeds, and a cross-landlord insert is rejected. The test database initializer also requires this table to have RLS enabled and forced, with at least one policy.
- **Focused PostgreSQL checks completed (2026-10-07):** the RLS and webhook integration suites passed with **56 tests** and one pending-deprecation warning against the isolated local `kodiflow_test` database. The dedicated local test container was stopped with its volume preserved. Those full suites were not run against Supabase; the separate guarded smoke check below tested the new table through the deployed app role.
- **Supabase application-role behavior check completed (2026-10-07):** `scripts/supabase_credit_application_rls_smoke.py` connected directly as `kodiflow_app`, verified that two synthetic landlords could each read only their own credit application, confirmed a valid same-landlord insert, and confirmed a cross-landlord insert was rejected. A separate `kodiflow_system` connection removed all synthetic fixtures in cleanup. The script restricts itself to the KodiLedger-dev project reference and does not print credentials. Supabase SQL Editor could not `SET ROLE kodiflow_app`, so the role-specific check used direct role connections instead.
- Verification: the focused authorization/OpenAPI contract file passed (30 tests); the lock-order concurrency test passed; and the full suite passed (**168 passed, 1 pending-deprecation warning**) on 2026-10-06. The rerun was performed after fixing the tenant lock-upgrade deadlock and making the RLS system-session assertion fixture-scoped.

## Goal

Verify one KodiLedger initiated Daraja sandbox STK request from initiation through callback receipt and durable webhook processing. An accepted STK request is not proof of payment, and status-query responses alone do not create KodiLedger payment or ledger records.

## Financial domain checkpoint - 2026-10-06

- The user accepted the rule that a completed payment assigned to a tenant with no unpaid invoice is recorded as an `AVAILABLE` payment credit for the remaining amount. No invoice allocation is created, and the full receipt remains in the ledger.
- The rule is implemented in the existing `InvoiceAllocationService`, shared by matched webhook reconciliation and unassigned-payment resolution. The payment credit, ledger, outbox, and related processing state remain in the caller's PostgreSQL transaction.
- Real PostgreSQL tests cover callback reconciliation without an invoice, unassigned-payment resolution without an unpaid invoice, and concurrent allocation of the same no-invoice payment. The full suite passed: 162 tests.
- Decision 7 is accepted: keep original credit amounts immutable and record uses in immutable payment-credit application rows. Automatically apply credit FIFO to the oldest unpaid invoice after payment allocation/resolution and when a new invoice is created; any remainder stays available.
- The application record, tenant/payment/credit/invoice PostgreSQL locks, invoice paid-state projection, and credit read-model `available_amount` are implemented. Refund, cancellation, expiry, and tenant-transfer policies remain undefined and unavailable. No public credit-application endpoint was added; payment and invoice workflows apply credits internally.
- The implementation was included in the full-suite run from 2026-10-06 (**168 passed**). The test's system-session assertion now scopes its count to the two landlord fixtures created by that test, so unrelated rows left by an interrupted earlier run do not affect it.

## Confirmed in the codebase

- The callback route is `POST /api/v1/webhooks/mpesa`.
- Callback handling checks the configured callback token and, outside `development` and `test`, the configured source IP allowlist.
- Callback IDs must match a KodiLedger recorded STK initiation before the callback is persisted and processed.
- The STK status-query endpoint does not return the payment metadata needed for financial reconciliation. Reconciliation requires the callback workflow.
- Never record Daraja passwords, consumer secrets, passkeys, callback tokens, or full tokenized callback URLs in this file or command output.

## Current checkpoint - 2026-10-05

- The user started Docker Desktop. `kodiflow_db` and `kodiflow_redis` are running, and PostgreSQL accepts connections.
- The local request table currently has `5 PENDING`, `2 SUCCEEDED`, and `2 CALLBACK_RECEIVED` records. One recent success status came from a Daraja query, not a callback; it has no payment transaction, allocation, credit, or ledger record. Refresh this snapshot before further action.
- The ngrok agent forwarded `https://trance-unstuffed-subpar.ngrok-free.dev` to local port `8001`. `docs/ngrok-callback-policy.yml` restricted the tunnel to the webhook path: public `GET /docs` returned `403`; public `GET /api/v1/webhooks/mpesa` returned `405` while the API was running.
- One callback POST reached the route and received HTTP `200`, with Daraja `ResultCode` `1037` (non-success). The database was missing the migration 0014 `locked_at` column, so the inbox row remained unprocessed. Migration 0014 was applied to the local database, and KodiLedger's non-success callback path then marked that row processed. No payment transaction, allocation, credit, or ledger entry was created for it.
- After the user confirmed the previous prompts were not received or resolved, one new KES 1 sandbox request was sent to the test number ending `9982` through local `POST /api/v1/payments/stk-push`. Daraja returned `ResponseCode` `0` (accepted for processing). Its callback was received and processed with `ResultCode` `1032` and description `Request Cancelled by user.` The callback links to no payment transaction; this was not a completed payment, and no allocation, credit, or ledger entry was created.
- The user confirmed that the latest prompt appeared on the handset. Its processed callback records a cancellation outcome, so handset delivery and the non-success callback path are confirmed; successful payment reconciliation is still unverified. To test that path, obtain authorization for a separate sandbox prompt and approve it on the handset. Do not initiate another prompt as part of this run.
- The API and ngrok processes are now stopped. The temporary process callback token was retired. Uvicorn's default access log included the callback query string, so future local runs use `--no-access-log`; never copy token-bearing inspector URLs into chat or documentation.
- The local `ngrok` command is available through the installed Microsoft Store package. Its config validates.
- Existing STK requests retain the callback URL supplied when each request was initiated. Changing `MPESA_CALLBACK_URL` now cannot retarget those requests to ngrok.
- A recent STK status query returned `ResponseCode` `0` and `ResultCode` `0`, but no corresponding callback was recorded. That query result is not sufficient to create KodiLedger accounting records.
- Do not send another STK prompt as part of this run. The newest request has a processed cancellation callback; check with the user before creating any further prompt.

## Procedure

### 1. Start local dependencies

Start Docker Desktop and wait until its engine is ready. From the repository root, start the local PostgreSQL and Redis services:

```powershell
docker compose up -d postgres redis
```

Confirm the database and Redis containers are running before proceeding. Apply pending local migrations in numeric order before starting the API. This test found that migration `0014_webhook_inbox_retries.sql` had not been applied; it was applied to the local `kodiflow_db` and adds the inbox retry columns, including `locked_at`. Keep this local development database separate from any shared or production database.

### 2. Start the ngrok tunnel

Use the installed ngrok agent or install it from the [official ngrok setup guide](https://ngrok.com/docs/getting-started/). Authenticate the agent using ngrok's setup instructions; never place its authentication token in this roadmap or in command output.

Forward the public HTTPS endpoint to local port `8001` and apply the workspace callback-only policy file:

```powershell
ngrok http 8001 --traffic-policy-file docs/ngrok-callback-policy.yml
```

Keep the tunnel running. Copy its current HTTPS forwarding origin (not the inspector address) for the next step. Confirm a public GET to `/docs` is denied by the edge policy before continuing. Avoid request history in the ngrok inspector because callback URLs contain the token.

### 3. Start KodiLedger with the current callback URL

In a separate PowerShell terminal at the repository root, set the callback URL to the current tunnel URL and run the API on port `8001`:

```powershell
$env:ENVIRONMENT = "development"
$env:DEBUG = "false"
$env:MPESA_CALLBACK_URL = "https://<current-ngrok-host>/api/v1/webhooks/mpesa"
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 48
$rng.GetBytes($bytes)
$env:MPESA_CALLBACK_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
[Array]::Clear($bytes, 0, $bytes.Length)
if ($env:MPESA_CALLBACK_TOKEN.Length -lt 32) { throw "Callback token generation failed" }
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Replace only `<current-ngrok-host>` with the host shown by the running ngrok agent. Do not include the ngrok inspector port or put the generated callback token in this file. The app appends the process-only token to the provider callback URL and validates it. Development mode skips the source-IP allowlist for this local tunnel test; never use this setting to weaken a deployed environment. The ngrok policy exposes only the callback path, while Swagger and the STK initiation endpoint remain local. `--no-access-log` prevents Uvicorn from printing query strings that contain the callback token.

Confirm `http://127.0.0.1:8001/docs` opens. A `GET` to the callback route should return `405 Method Not Allowed`, because it accepts `POST`; this only confirms routing, not Safaricom callback delivery.

### 4. Check for an existing request before creating another

Inspect the local `stk_push_requests` table or the administrator-only unresolved STK queue. Reuse an existing unresolved app-initiated request if appropriate. Record its checkout ID privately for correlation; do not paste tokens or credentials into logs or documentation.

Existing requests retain their original callback URL; they cannot test a newly configured ngrok callback. Check unresolved requests and confirm the test phone has no outstanding prompt before creating another. After explicit confirmation to continue, submit at most one new sandbox STK request through KodiLedger Swagger at `http://127.0.0.1:8001/docs` or local `POST /api/v1/payments/stk-push`, using the confirmed test phone in `254XXXXXXXXX` format and amount. Save the returned `MerchantRequestID` and `CheckoutRequestID` outside this roadmap. `ResponseCode` equal to `0` means Daraja accepted the request; it does not mean a payment completed.

If the response is `422`, inspect request validation. For `400`, inspect app configuration. For `502`, inspect Uvicorn output for the Daraja failure. Do not retry until the first request's outcome is clear.

### 5. Verify callback delivery

- Uvicorn access logs are disabled to prevent token-bearing callback URLs from being logged. Confirm callback receipt and processing by matching the request in the local database; do not copy or share request URLs from the ngrok inspector because they contain the callback token.
- Confirm the callback's merchant and checkout IDs match the app-initiated request. A simulator-generated request with unrelated IDs is intentionally rejected.
- Confirm callback delivery from the raw inbox row correlated with the initiation IDs and its processing status. A browser GET, a status query, or the original STK acceptance response does not prove callback delivery.

### 6. Verify durable processing

For the correlated checkout ID, inspect the local database:

```sql
SELECT id, merchant_request_id, checkout_request_id,
       mpesa_receipt_number, processed, created_at
FROM raw_payment_webhooks
WHERE checkout_request_id = '<CheckoutRequestID>';
```

Check the associated `stk_push_requests` row. For a genuinely successful payment callback, verify the expected transaction and reconciliation effects. Do not send a fabricated success callback to a shared or working database; it could create financial records. If testing transport synthetically, use a non-success result and IDs from a recorded local initiation.

## Later: stable deployment

ngrok is for local development and sandbox testing; its endpoint is useful only while its tunnel is running. For a persistent callback URL, deploy the API to a hosting account you control, configure the provider callback URL and secrets there, and route the public path to this app. The public custom domain previously returned `404`; its DNS/hosting owner still needs to be identified before changing that route.
