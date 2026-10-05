# KodiLedger Security

This document records the security controls present in the repository and the gaps between those controls and the intended production architecture. It is implementation documentation, not a security certification. The goals are to keep landlord data isolated, preserve correct and auditable financial state, constrain privileged database work, and process external payment events without treating Redis or a payment-initiation response as financial truth.

Status labels describe the current repository: **IMPLEMENTED** means code or migrations exist; **PARTIALLY IMPLEMENTED** means a control exists but is not connected end to end or has a material limitation; **PLANNED / FUTURE** means architecture or product documentation calls for it but it is not implemented.

## 1. Security Principles

- **Defense in depth — PARTIALLY IMPLEMENTED.** The design combines API authorization, PostgreSQL row-level security (RLS), database constraints, Redis coordination, and transactional financial updates. OIDC identity resolution, role/membership lookup, and transaction-local RLS context are connected on the protected landlord BFF path; broader business routes and PostgreSQL-backed isolation proof are not present.
- **Least privilege — PARTIALLY IMPLEMENTED.** A `kodiflow_system` database role is separated from the ordinary application role and receives `BYPASSRLS` for trusted webhook/worker operations. Its broad table privileges make its credentials highly privileged. The migrations revoke access to internal webhook/outbox tables from `kodiflow_app`; deployment provisioning and complete application-role grants are outside these migrations.
- **Tenant isolation — PARTIALLY IMPLEMENTED.** Landlord ownership columns, landlord-scoped RLS policies, and persisted user-to-membership mappings exist in the schema/migration. The landlord BFF resolves scope from the active local membership and binds it to transaction-local RLS settings. There is no PostgreSQL-backed cross-landlord test, so end-to-end tenant isolation is not established.
- **PostgreSQL financial authority — IMPLEMENTED.** Payment processing, transactions, allocations, credits, ledger entries, and outbox work are persisted in PostgreSQL. Redis is a coordination layer, not financial truth.
- **Fail-safe financial processing — PARTIALLY IMPLEMENTED.** Financial reconciliation and its outbox record share a database transaction, with rollback on service errors. External callback authenticity is not verified, and broader failure scenarios need tests.
- **Idempotency — IMPLEMENTED for payment receipt claims.** Redis provides a fast-path lock; a PostgreSQL unique receipt claim is authoritative.
- **Auditability — PARTIALLY IMPLEMENTED.** Raw callback payloads and processing/payment records persist, but a general actor/action audit system is not present.
- **Secret isolation — PARTIALLY IMPLEMENTED.** Backend settings load from environment or `.env`, `.env` is ignored by Git, and the example file uses placeholders. Deployment secret management is not implemented here.
- **Explicit authorization — PARTIALLY IMPLEMENTED.** JWT bearer verification, role/permission helpers, and two protected BFF context endpoints exist. Most business APIs and identity lifecycle are not implemented.
- **External payment callbacks — PARTIALLY IMPLEMENTED.** Callback shape validation, a shared URL token and configured source-IP filtering outside development/test, exact initiated-request ID correlation, raw persistence, idempotency, and transactional reconciliation exist. There is no provider signature verification, and production token management plus proxy/IP-list configuration must be verified operationally.

## 2. Security Architecture

The intended request path is:

```text
Client
  -> HTTPS (deployment responsibility)
  -> Authentication
  -> RBAC
  -> Application authorization and landlord scope
  -> PostgreSQL RLS context
  -> Database privileges and constraints
```

| Layer | Current status | Repository evidence / limitation |
| --- | --- | --- |
| HTTPS | PLANNED / deployment-dependent | No TLS termination or deployment configuration is in this repository. |
| Authentication | PARTIALLY IMPLEMENTED | HTTP Bearer OIDC JWT signature/issuer/audience/expiry verification and local identity/membership resolution exist. Hosted login, trusted account provisioning, refresh, revocation, and configured provider values are not present. |
| RBAC | PARTIALLY IMPLEMENTED | Role/permission matrix and checks exist; only the two BFF `/me` endpoints use them. |
| Application authorization | PARTIALLY IMPLEMENTED | The BFF endpoints check role and permission. General landlord resource APIs and ownership checks are not present. |
| PostgreSQL RLS | PARTIALLY IMPLEMENTED | Policies and a transaction-local session-context helper exist. The helper is used by the landlord BFF only; no end-to-end cross-landlord integration test exists. |
| Database permissions | PARTIALLY IMPLEMENTED | A separate system role and internal-table grants/revokes are migrated. The system role bypasses RLS; ordinary-role provisioning and privilege verification are deployment concerns. |

Do not interpret the diagram as proof that every layer protects every current route. In particular, STK Push and callback routes do not declare authentication or authorization dependencies.

## 3. Authentication

**PARTIALLY IMPLEMENTED.** `app/security/authentication.py` verifies bearer JWT signatures using the configured OIDC JWKS URL, requires an explicitly configured asymmetric algorithm, and validates issuer, audience, expiry, issued-at, and subject. The JWKS lookup runs off the async request thread and has a bounded timeout/cache. Missing provider configuration and JWKS connectivity failures return HTTP 503; invalid tokens return HTTP 401. Provider claims such as `role` and `landlord_id` are ignored for authorization.

`app/security/identity.py` maps the verified `(iss, sub)` pair to an active `app_users` row and exactly one active KodiLedger membership. The resulting principal's user ID, role, landlord ID, and tenant ID come from that membership. Unknown/inactive identities are rejected, absent or ambiguous membership is denied, and `SYSTEM` cannot be used as an application bearer role. Multiple active memberships currently require a future membership-selection flow. Memberships must be provisioned by a trusted operator; self-enrollment is not implemented.

Migration `0013_authenticated_identity.sql` adds the provider-neutral identity schema: unique external issuer/subject mapping, active user records, constrained application memberships, and read-only grants to `kodiflow_app`. It has not been applied to a database. Configure `OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, and `OIDC_SIGNING_ALGORITHMS` for the chosen provider before accepting its tokens.

The landlord and caretaker BFF `/me` routes depend on bearer authentication and role/permission checks. Payment initiation and M-Pesa callback routes currently do not. The ordinary request dependency resolves identity with `get_db`; protected landlord routes then set transaction-local RLS context on that same request-scoped session. This has unit coverage but no PostgreSQL-backed authenticated identity/RLS integration test.

## 4. Authorization and RBAC

**PARTIALLY IMPLEMENTED.** `app/security/roles.py` defines `LANDLORD`, `CARETAKER`, `TENANT`, `ADMIN`, and `SYSTEM`. `app/security/permissions.py` defines resource permissions; `app/security/authorization.py` maps role to permission and provides FastAPI dependencies. The intended caretaker role has narrower operational permissions than landlord, tenant access is limited, admin has all defined permissions, and system has a narrow application permission set.

Those definitions are not proof of complete API enforcement. Currently the landlord BFF `/me` endpoint requires `LANDLORD` plus `PROPERTY_READ`; caretaker `/me` requires `CARETAKER` plus `UNIT_READ`. The STK Push and webhook endpoints do not use these dependencies. The permission matrix does not implement resource ownership by itself. Landlord/caretaker/tenant scope is derived from the local membership record, but broad resource APIs and resource-level ownership checks are not implemented. Tenant memberships reference the tenant and landlord; a complete caretaker lifecycle and tenant self-service flow are not present.

| Role | Current route enforcement |
| --- | --- |
| `LANDLORD` | Allowed only on `/api/v1/bff/landlord/me` through explicit role and permission checks. |
| `CARETAKER` | Allowed only on `/api/v1/bff/caretaker/me` through explicit role and permission checks. |
| `TENANT` | No current API route grants tenant access. |
| `ADMIN` | Permission matrix defines permissions, but no current API route grants admin access. |
| `SYSTEM` | Rejected as a normal bearer membership; separate trusted database role is used for system/webhook/background workflows. It is not a human application role. |

**PLANNED / FUTURE:** apply role and permission dependencies to business API contracts and test both role denial and cross-landlord resource denial. Membership selection for identities with multiple active memberships also remains future work.

## 5. Multi-Tenant Isolation

Landlord ownership is represented through `landlord_id` on records including properties, units, tenants, invoices, ledger entries, payment processing, payment transactions, unassigned payments, utility readings, and device tokens. Allocation and credit rows are scoped through their parent payment transaction. Foreign keys connect much of the property, tenancy, invoice, and payment graph.

The intended invariant is that Landlord A cannot read or change Landlord B's property or financial data. The intended defense in depth is application authorization plus PostgreSQL RLS. RLS policies scope normal access by `app.current_landlord_id()`.

**PARTIALLY IMPLEMENTED:** `set_rls_context()` and `get_rls_db()` set transaction-local landlord, user, and role settings from the canonical principal, and the landlord BFF endpoint uses that dependency. The principal is resolved from a verified OIDC `(iss, sub)` and an active local membership; client/token role and ownership claims are not authoritative. There are no production resource routes proving end-to-end isolation, and no database-backed test that an authenticated Landlord A is denied Landlord B data. The RLS foundation and this narrow context wiring are not equivalent to complete authenticated tenant isolation.

## 6. PostgreSQL Row-Level Security

**PARTIALLY IMPLEMENTED: the PostgreSQL RLS foundation and a limited authenticated context path exist.** The migration chain must be read together: migration `0010` defines `app.current_landlord_id()`, `app.current_user_id()`, and `app.current_role()` from PostgreSQL settings and initially uses role-aware policies. Migration `0011` removes the `app.current_role()` function and replaces those policies with landlord-scope-only policies. The application helper sets all three settings transaction-locally from the authenticated principal; the role setting no longer participates in the final policies. `current_user_id()` is defined but is not used by the final policies. The landlord BFF is the only route currently exercising this path, and there is no PostgreSQL-backed cross-landlord test.

Migration `0010` enables RLS on these 13 tables and forces RLS on the same tables:

`landlords`, `properties`, `units`, `tenants`, `invoices`, `ledger_entries`, `payment_processing`, `payment_transactions`, `payment_allocations`, `payment_credits`, `unassigned_payments`, `utility_readings`, and `user_device_tokens`.

It does not enable RLS on `raw_payment_webhooks` or `outbox_events`. Migration `0011` revokes all privileges on those two tables from `kodiflow_app` and grants CRUD privileges to `kodiflow_system`.

The final policies generally permit `SELECT`, `INSERT`, and `UPDATE` only where the row's `landlord_id` equals `app.current_landlord_id()`. `landlords` uses `id` as the scope. Allocations and credits use an `EXISTS` check through `payment_transactions.landlord_id`. Final delete policies deny deletes (with `USING (false)`) for landlords, ledger entries, payment processing, transactions, allocations, credits, unassigned payments, utility readings, and device tokens; other listed tables use landlord scope for delete. Landlord insertion is denied by policy. The system role bypasses RLS at the role level rather than through a policy exception.

`kodiflow_system` is created as `LOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `BYPASSRLS`, and is granted CRUD on all public-schema tables plus default table privileges. It is used by webhook and outbox worker database sessions. `kodiflow_app` is referenced in revokes but is not created or fully granted by migrations 0010/0011. The ordinary application connection is configured separately as `DATABASE_URL`; the trusted workflow connection uses `SYSTEM_DATABASE_URL`.

The intended reason for separate roles is to keep normal application access under RLS and reserve bypass capability for trusted webhook/background operations. The system connection has broad privileges and must be protected as a high-trust credential. No RLS integration test confirms actual database policy behavior under authenticated tenant context. Unit tests asserting mocked `set_config()` parameters do not prove application-to-RLS isolation; manual `psql set_config()` checks, if performed, would not prove that integration either.

## 7. Database Security

- **Roles and sessions — PARTIALLY IMPLEMENTED:** async SQLAlchemy engines and session factories are separate for `DATABASE_URL` and `SYSTEM_DATABASE_URL`. Webhook repository dependencies and the outbox worker use the system session. The migrations harden the system role and restrict it from ordinary use; the exact deployment credentials/privileges for the app role must be verified outside this repository.
- **RLS — PARTIALLY IMPLEMENTED:** see section 6. RLS policies apply only when the connection role does not bypass RLS and the transaction has the correct landlord context.
- **Relational constraints — IMPLEMENTED:** migrations use foreign keys, unique constraints, and checks, including unique M-Pesa receipt claims, unique allocation/payment relationships, positive financial amounts, and nonnegative property charges. These are the database backstop for application workflows.
- **Financial precision — IMPLEMENTED:** financial amounts use PostgreSQL `NUMERIC`/Python `Decimal` where modeled and processed; integer KES amounts are accepted for STK initiation. PostgreSQL remains authoritative for persisted financial state.
- **Transaction boundaries — IMPLEMENTED for callback reconciliation:** raw webhook persistence, receipt claim, payment transaction, allocation/credit, ledger update, processing status, and outbox event use the callback's system database session. The service commits the workflow or rolls it back on caught exceptions. A database rollback cannot undo a payment already executed by Safaricom.
- **Restricted access — PARTIALLY IMPLEMENTED:** internal raw webhook and outbox tables are withheld from `kodiflow_app` by migration 0011 and granted to the system role. Credential storage, network access rules, backups, and operational DB access controls are deployment responsibilities and are not defined here.

PostgreSQL is authoritative because durable uniqueness constraints and transactions—not cache state—decide whether receipt processing and accounting effects commit.

## 8. Financial Security

**IMPLEMENTED in the callback workflow:** successful payments are claimed in `payment_processing` using an insert with conflict-do-nothing on the unique receipt. The claim, normalized `payment_transactions` row (also with a unique receipt), allocation or unassigned-payment record, ledger credit for a matched tenant, processing status, and outbox event are coordinated in the database transaction. A failure before commit triggers rollback.

Invoice allocation locks the oldest unpaid invoice row (`FOR UPDATE` in the repository), then reads the allocated total and applies a partial or full payment. Excess over the remaining invoice balance becomes an available payment credit. A payment with no matching active tenant is persisted as unassigned and does not follow the matched-tenant ledger/outbox branch in `ReconciliationService`.

Idempotency uses two layers:

```text
Redis SET NX lock (fast-path, 24-hour TTL)
        -> PostgreSQL unique receipt claim (authoritative)
        -> reconciliation, allocation, ledger and outbox in one transaction
```

Redis unavailable is treated as a fast-path bypass by `IdempotencyService`; processing continues to PostgreSQL. Duplicate receipt claims return without repeating financial effects. The payment initiation endpoint explicitly treats STK Push as initiation only; it does not itself write a ledger entry or mean that payment completed.

These controls protect implemented paths, not arbitrary manual adjustments. The repository does not show a general audited reversal/adjustment workflow or comprehensive failure-injection tests for every financial boundary.

## 9. M-Pesa / Webhook Security

**PARTIALLY IMPLEMENTED.** `POST /api/v1/webhooks/mpesa` parses a Pydantic callback model, persists the JSON payload in `raw_payment_webhooks`, extracts receipt/amount/phone for successful callbacks, rejects missing/invalid successful-payment metadata in the service, and uses Redis plus the PostgreSQL receipt claim to avoid duplicate financial effects. Payment processing, reconciliation, and outbox writes are transactional. Failed-provider callbacks are recorded and committed without creating a successful payment transaction. The webhook uses `get_system_db()` because processing requires trusted database access beyond normal RLS scope.

**Not implemented:** the route does not authenticate the callback sender or verify a provider signature/HMAC, shared secret, or network allowlist. Pydantic validates structure and types; it does not establish that Safaricom sent the request. Callback metadata is accepted as input and then used to select a receipt, amount, phone, and landlord mapping via configured shortcode. Replay/duplicate protection limits repeated effects for a receipt, but does not prevent forged first-seen callbacks.

Error behavior also needs hardening: the service returns an internal exception string in `ResultDesc`, and diagnostic `print()` statements include exception data and reconciliation results. Raw callbacks are intentionally persisted and contain personal/payment information. External provider account security, callback URL exposure, provider-side controls, and reconciliation with provider records remain operational responsibilities.

## 10. API Security

- **Input validation — IMPLEMENTED:** FastAPI/Pydantic request models validate STK phone format (`254` plus nine digits) and positive integer amount; unknown STK fields are forbidden. Callback models validate the expected nested shape while ignoring extra fields.
- **Rate limiting — IMPLEMENTED for STK initiation:** Redis Lua performs atomic fixed-window increments. The default is five requests per client IP per 60 seconds, configurable by environment. Exceeding the limit returns HTTP 429 with retry/rate headers. The callback route has no rate limit.
- **Authentication/authorization — PARTIALLY IMPLEMENTED:** only the landlord/caretaker BFF context endpoints require bearer auth and role/permission checks. STK Push and webhook routes are unauthenticated in the current application.
- **Error handling — PARTIALLY IMPLEMENTED:** STK Push maps validation/upstream/unexpected errors to 400/502/500. However, a temporary diagnostic path prints a traceback; some upstream exceptions can include response text. Webhook errors expose exception text in the response. Avoid returning internal exception, SQL, credential, or provider response details to clients.
- **CORS — CONFIGURABLE:** origins come from `CORS_ALLOWED_ORIGINS` and default to an empty list. CORS is a browser policy, not authentication or authorization.
- **Sensitive data exposure — PARTIALLY IMPLEMENTED:** response schemas constrain the STK response, but payment/webhook diagnostics and raw audit payload handling need stricter logging/redaction controls. No general sensitive-field response policy exists.

## 11. Redis Security

Redis supports M-Pesa receipt locks (24-hour TTL) and STK Push fixed-window rate limits. It is not the financial system of record. Idempotency lock values use random tokens, and release uses a Lua compare-and-delete so one request cannot delete another request's lock.

**Failure behavior differs by use:** idempotency acquisition logs a warning and bypasses the Redis lock on Redis errors, relying on PostgreSQL uniqueness. The rate limiter raises an error on Redis operation failure; no fallback limiter is implemented, so STK initiation fails rather than silently removing the limit. No repository-level Redis authentication/TLS policy is specified; connection configuration is supplied through `REDIS_URL`. Redis-unavailable behavior is not covered by the current integration tests.

## 12. Kafka / Outbox Security

**IMPLEMENTED:** a matched payment's outbox row is created in the same PostgreSQL transaction as its financial effects. A worker uses the trusted system session to claim a bounded batch in deterministic order with `FOR UPDATE SKIP LOCKED`, commits the claims before Kafka I/O, and records each event outcome independently. Batch size, Kafka linger, polling interval, and stale-lock timeout are configurable (`OUTBOX_BATCH_SIZE=100`, `OUTBOX_MAX_BATCH_WAIT_MS=1000`, `OUTBOX_POLL_INTERVAL_MS=500`, and `OUTBOX_LOCK_TIMEOUT_SECONDS=300` by default). Failed events are retried independently with exponential backoff capped at 300 seconds; after five total failed attempts each event is marked failed. Pending claims older than the configured 300-second default can be reclaimed. Outbox event idempotency keys are unique. The Kafka producer enables producer idempotence.

Kafka delivery occurs after the financial transaction commits. A Kafka outage therefore does not need to roll back the financial commit; the durable outbox retains work for retry. A crash after publish but before marking the row published can cause redelivery. Producer idempotence does not guarantee that every downstream consumer applies each business effect exactly once; consumers must deduplicate using event identity/idempotency key. No consumer implementation is present in the repository.

## 13. Secrets and Sensitive Configuration

Settings are read through Pydantic settings from environment variables and `.env`. Configuration includes PostgreSQL URLs/credentials, Redis URL, M-Pesa consumer key/secret/passkey/shortcode and callback URL, OIDC issuer/audience/JWKS settings, CORS origins, and Kafka bootstrap/topic settings. `.gitignore` excludes `.env` and permits `.env.example`; the example uses placeholders. Never commit secrets, and keep database, Redis, Kafka, OIDC client credentials (if later required), and M-Pesa credentials server-side. Do not put secrets or bearer tokens in browser logs or public responses.

The Daraja OAuth token is cached in process memory and sent to the provider as a bearer credential. The M-Pesa client also constructs a request password from the configured shortcode/passkey. No production secret manager, rotation process, or environment-specific secret policy is implemented in this repository. Do not log credentials, JWTs, OAuth tokens, callback authorization material, full sensitive payment payloads, or unnecessary personal identifiers.

## 14. Logging and Auditability

Raw webhook rows retain provider request JSON and identifiers; normalized payment/processing records retain receipt, merchant/check-out identifiers, amount, phone, processing status, and related financial records. These records support callback investigation and reconciliation, but are not a complete actor-based audit log. No general audit trail for login, property edits, manual adjustments, or authorization decisions is implemented.

The M-Pesa client logs request timing/status and cache events. The payment endpoint logs failures and temporarily prints full unexpected tracebacks. The webhook service prints reconciliation details and exception text; its error response includes the exception string. These paths can expose operational or personal data. Logs should avoid secrets, tokens, full callback bodies, full phone numbers, and unfiltered exception/provider bodies. Correlation IDs are not consistently implemented; merchant/check-out IDs and receipts are the current payment correlation identifiers.

## 15. Failure and Recovery Security

| Event | Current behavior | Classification / remaining gap |
| --- | --- | --- |
| PostgreSQL failure during callback | Service attempts rollback and returns an error result. | Financial consistency control; database outage integration test is missing. |
| Redis unavailable during payment idempotency | Fast-path is bypassed; PostgreSQL receipt uniqueness remains authoritative. | Correctness fallback is implemented; Redis outage scenario test is missing. |
| Redis unavailable during rate limiting | Rate limiter raises an error. | Fails closed for this endpoint, but no explicit dependency-failure HTTP mapping/test exists. |
| Duplicate callback | Raw callback is persisted; existing receipt claim prevents another financial application. | Implemented; duplicate integration coverage exists. |
| Concurrent callbacks | Redis lock plus unique PostgreSQL claim coordinates by receipt. | Implementation exists; authenticated behavior and Redis-free race testing need coverage. |
| Reconciliation exception | Database transaction is rolled back and acquired Redis lock is released. | Unit test covers this service path. An external payment itself cannot be rolled back. |
| Stale Redis lock | If PostgreSQL has no receipt claim, service proceeds; Redis TTL eventually expires. | Implemented; specific stale-lock integration test is absent. |
| Worker/Kafka failure | Outbox row is rescheduled with backoff or marked failed after attempt limit. | Reliability control; publication may be duplicated around publish/mark crash window. |
| Stale outbox claim | Locks older than `OUTBOX_LOCK_TIMEOUT_SECONDS` (300 seconds by default) may be claimed again. | Implemented; PostgreSQL concurrency and stale-claim integration tests cover recovery. |
| Provider failure | STK initiation maps upstream errors to 502; callback failure status is recorded. | Provider completion/reconciliation recovery jobs are not implemented. |

## 16. Security Testing

Current tests include:

- **Authentication and endpoint role checks:** `app/Tests/security/test_bff_authorization.py` checks missing/invalid bearer credentials and role denials/allows for the two BFF `/me` routes. It overrides the authenticated-principal dependency to isolate RBAC behavior.
- **Permission matrix:** `app/Tests/security/test_authorization.py` checks role permission definitions and helper dependencies in isolation.
- **Authentication context:** `app/Tests/security/test_authentication.py` checks OIDC verification parameters, rejected signatures/configuration, local membership-derived role/scope, unlinked/inactive/system/ambiguous memberships, and request-to-request isolation with fake sessions. This is not a PostgreSQL identity lookup or RLS integration test.
- **RLS context helper:** `app/Tests/security/test_rls.py` checks that mocked SQL execution receives landlord/user/role settings using transaction-local settings. This is not a PostgreSQL policy or authenticated cross-tenant integration test.
- **Webhook rollback:** `app/Tests/security/test_webhook_service.py` forces reconciliation failure and checks rollback and Redis lock release.
- **Webhook idempotency:** `app/Tests/integration/test_webhook_integration.py` verifies duplicate callback behavior and persisted single processing/allocation/ledger/outbox effects; it also covers an unassigned payment path.
- **Rate limiting:** integration tests check fixed-window behavior and that the sixth STK Push request is rejected after the default five-request limit.
- **Concurrency/outbox:** test modules include concurrent payment scenarios and outbox worker/publisher coverage. These do not establish consumer-side duplicate-event handling or authenticated financial isolation.

The repository does not contain security tests proving authenticated tenant isolation, actual RLS policy behavior, or database-role privileges.

### Security Test Gaps

- Authenticated Landlord A versus Landlord B cross-tenant read/write denial, including all resource relationships.
- End-to-end OIDC landlord identity resolution and RLS context propagation using a real PostgreSQL session and non-bypass role.
- RBAC enforcement across each implemented business route and resource ownership checks.
- Database role privilege checks for `kodiflow_app` and `kodiflow_system`, including raw webhook/outbox access and RLS bypass expectations.
- Redis unavailable scenarios for both idempotency and rate limiting; stale lock recovery.
- PostgreSQL unavailable scenarios during callback persistence, claim, and financial commit.
- Deadlock and concurrent invoice-allocation scenarios under real database contention.
- Duplicate outbox delivery and duplicate consumer-event application behavior.
- Forged callback rejection / callback sender authentication tests; no such verification is currently implemented.

## 17. Threat Model

| Threat | Current mitigation | Remaining gap |
| --- | --- | --- |
| Malicious tenant tries another landlord's records | Verified provider identity resolves to a local tenant/landlord membership; RLS policies scope by landlord. | No cross-landlord integration tests or broad protected resource APIs. |
| Stolen/compromised authentication credential | OIDC JWT signature/issuer/audience/expiry checks protect the two BFF routes; inactive/unlinked accounts are rejected. | No hosted login lifecycle, refresh/revocation, or broad protected API coverage. |
| Duplicate/replayed payment callback | Redis lock, unique PostgreSQL receipt claim, unique normalized receipt, transaction. | A forged first-seen callback is not stopped by idempotency; raw callback retention needs operational controls. |
| Forged or malformed webhook | Pydantic validation, production/staging callback token, peer-IP allowlist, and exact merchant/checkout ID correlation to an initiated STK request. | Daraja callback has no provider signature in this implementation; token must be kept secret, IP list current, and proxy trust configured at deployment. IP filtering is bypassed in `development`/`test`; token validation is bypassed there only when no token is configured. |
| Unauthorized financial record modification | Database constraints, landlord RLS policies, separated system/app DB roles. | System role has broad CRUD and bypasses RLS; identity propagation and privilege checks are incomplete. |
| Leaked database credentials | Separate system and ordinary connection settings; `.env` is ignored by Git. | No production secret manager/rotation/network controls; system credential is especially privileged. |
| Leaked M-Pesa credentials | Credentials are backend settings and used by the server-side client. | No repository-defined production secret manager/rotation; logs and deployment handling require hardening. |
| Redis compromise/failure | PostgreSQL remains authoritative for receipt claims; idempotency lock release checks token. | Redis connection hardening is unspecified; rate limiting has no fallback and outage tests are missing. |
| Kafka/outbox duplication | Durable outbox, unique event idempotency key, producer idempotence, retry/claiming. | Publish/mark crash window and consumer deduplication remain; no consumer is present. |
| Insider misuse | Database roles separate normal and trusted operations; important payment records persist. | System role is broad; actor-level audit and operational access monitoring are not implemented. |
| Sensitive logging | Some API errors return generic messages. | Other paths print tracebacks, exception/provider details, reconciliation data, or callback errors; redaction is incomplete. |

## 18. Security Roadmap

**Current implementation:** PostgreSQL RLS foundation and landlord policies; separate application/system sessions; trusted system database role; configurable OIDC JWT verification; provider identity mapped to KodiLedger-owned active memberships; role/permission helpers; BFF authorization checks; webhook persistence/audit records; callback shared-token verification, source-IP filtering, and initiated-request correlation; Redis idempotency and STK rate limiting; PostgreSQL receipt claims; transactional reconciliation and outbox; retrying outbox worker.

**Next, aligned with the documented Phase 3 work:** select/configure the OIDC provider; apply migration 0013 to a development/test schema and provision initial memberships; add membership selection for identities with multiple memberships; add PostgreSQL-backed identity/RLS isolation tests; apply RBAC and ownership checks to business API contracts; configure and verify production ingress/proxy trust and Safaricom's current callback IP list; protect payment initiation; remove exception/body leakage from responses and logs.

**Later, documented production-hardening direction:** production secret management and rotation; deployment TLS/network controls; security/operational alerting and observability; incident response/runbooks; reliability/failure-injection testing; penetration/security review. These are roadmap items, not current controls.

## 19. Security Invariants

- PostgreSQL is authoritative for persisted financial state.
- Redis is a coordination and rate-limiting layer, not the financial source of truth.
- The intended access rule is that a landlord cannot access another landlord's property or financial records; current authenticated end-to-end enforcement remains incomplete.
- A repeated M-Pesa receipt must not create duplicate financial effects; PostgreSQL uniqueness and transaction processing enforce this for the callback path.
- Payment reconciliation, allocation, ledger effects, and the matched-payment outbox event commit together or roll back together.
- Secrets and provider credentials remain server-side and must not be committed to source control.
- STK Push initiation is not evidence that an external payment completed; successful callback reconciliation is a separate step.
- Payment/callback records must remain available for operational reconciliation; raw callbacks contain sensitive data and require controlled access and retention.
- Outbox delivery may be repeated; downstream consumers must be idempotent before applying business effects.
