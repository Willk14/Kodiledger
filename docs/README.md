# KodiLedger

KodiLedger is a rental property management and payment reconciliation platform for landlords, caretakers, and tenants. Its backend receives M-Pesa payment events, reconciles payments against rental obligations, and records financial effects in PostgreSQL.

## 1. Overview

Rental payments can be difficult to match and track across M-Pesa messages, manual records, and property spreadsheets. KodiLedger is designed to help property owners and caretakers manage rental operations while giving tenants a clear way to pay. The core backend workflow tracks an external payment from initiation through callback confirmation and reconciliation, with database transactions and durable records supporting correctness and auditability.

## 2. Core Product Flow

```text
STK Push request
    -> Safaricom M-Pesa
    -> asynchronous callback
    -> webhook audit record and receipt claim
    -> reconciliation and invoice allocation
    -> payment credit for overpayment or no unpaid invoice
    -> ledger and transactional outbox
    -> Kafka publisher/worker
```

An STK Push response means only that the payment request was initiated. A later successful callback is processed and reconciled before financial effects are recorded. Duplicate receipt claims do not repeat those effects.

## 3. Architecture

```text
Next.js / React PWA (planned; no frontend application in this repository)
                          |
                       FastAPI
                          |
                Application services
                          |
                    Repositories
                          |
                     PostgreSQL
                    /           \
                 Redis       Transactional outbox
                                  |
                                Kafka
```

- **API:** FastAPI routes validate requests and connect dependencies to application services.
- **Services:** own workflows and transaction boundaries, including payment initiation and webhook reconciliation.
- **Repositories and models:** use SQLAlchemy with asynchronous PostgreSQL sessions.
- **PostgreSQL:** authoritative store for payment, allocation, credit, ledger, audit, and outbox records.
- **Redis:** coordination, STK rate limiting, and an idempotency fast path; it is not the financial authority.
- **M-Pesa Daraja:** receives STK requests and sends asynchronous callbacks.
- **Outbox and Kafka:** the outbox stores durable publication work in PostgreSQL; a worker publishes events and records retry or completion state.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed design.

## 4. Technology Stack

| Area | Technology verified in the repository |
| --- | --- |
| Backend/API | Python, FastAPI, Uvicorn |
| Persistence | PostgreSQL 15, SQLAlchemy async, asyncpg |
| Coordination/cache | Redis |
| Events | PostgreSQL transactional outbox, Kafka, aiokafka |
| Payments | Safaricom M-Pesa Daraja API |
| Authentication foundation | PyJWT OIDC access-token verification; local KodiLedger membership lookup |
| Testing | pytest, pytest-asyncio, HTTPX |
| Local infrastructure | Docker Compose for PostgreSQL, Redis, and Kafka |
| Frontend | Next.js / React / TypeScript / PWA is described in product architecture; frontend source is not present here |

Pinned Python package versions are listed in [requirements.txt](requirements.txt).

## 5. Current Implementation Status

| Status | Capabilities |
| --- | --- |
| Implemented | PostgreSQL schema and financial records; SQLAlchemy async sessions; M-Pesa OAuth token caching and STK Push initiation; callback ingestion and raw webhook persistence; Redis idempotency and rate limiting; PostgreSQL receipt claims; reconciliation, invoice allocation, payment credits, ledger writes, and transactional outbox; Kafka publisher/worker retry path; separate application and system database sessions. |
| Foundation / partial | OIDC JWT verification resolves a provider issuer/subject to one active local account membership. RBAC protects selected landlord, caretaker, tenant, and admin routes; user-scoped business routes use transaction-local RLS context. The OIDC identity schema is migration 0013 and must be applied before lookup works. |
| In progress | Complete login and account provisioning lifecycle; extend authenticated route coverage and resource ownership enforcement; validate deployed RLS role provisioning; callback sender authentication; sensitive error/log redaction. |
| Planned / not in this repository | Next.js/React PWA, notification workflows, and broader operational/reporting API contracts described by the PRD. |

RLS policies and the system database role are a database foundation; they do not prove end-to-end tenant isolation in every deployment. See [docs/auth.md](docs/auth.md) for the implemented route matrix and [docs/SECURITY.md](docs/SECURITY.md) for evidence and remaining gaps.

## 6. Financial Integrity Model

- PostgreSQL is authoritative for persisted financial state; Redis is not.
- Reconciliation and related payment records are written transactionally.
- A repeated M-Pesa receipt must not create duplicate financial effects.
- Invoice allocations and unapplied tenant credits are persisted as separate records.
- The ledger provides durable financial history.
- An outbox row is committed with the matched payment workflow so asynchronous publication can be retried after commit.

See [docs/SECURITY.md](docs/SECURITY.md) and [docs/DATABASE.md](docs/DATABASE.md).

## 7. Security

Implemented controls include request-model validation, STK Push rate limiting, Redis idempotency backed by a PostgreSQL receipt claim, webhook audit persistence, callback shared-token and source-IP checks outside development/test, initiated-request ID correlation, transaction-local RLS settings in the RLS dependency, and separate application/system database sessions. OIDC verification checks the configured issuer, audience, expiry, and asymmetric signing key; role and domain scope are resolved from local membership data.

Authentication is not applied across all business routes. Selected property, unit, tenant, invoice, payment, ledger, unassigned-payment, BFF, and admin operator routes are bearer-protected with role/permission checks; STK initiation has no user authentication, and the webhook uses a shared URL token, source-IP filter, and initiated-request correlation rather than user bearer auth or provider signature verification. RLS is partial and deployment role provisioning must be verified. Do not treat the repository as production-ready. See [docs/auth.md](docs/auth.md) and [docs/SECURITY.md](docs/SECURITY.md).

## 8. Repository Structure

```text
app/
  api/             FastAPI routes
  core/            Settings, database sessions, and shared dependencies
  integrations/    M-Pesa and Kafka integrations
  models/          SQLAlchemy models
  repositories/    Persistence queries
  schemas/         API input/output models
  security/        Authentication, authorization, and RLS helpers
  services/        Application workflows
  Tests/           Unit, security, and integration tests
  workers/         Background outbox processing
db/migrations/     Ordered PostgreSQL SQL migrations
docs/              Product, architecture, database, and security documents
```

## 9. Prerequisites

- Python 3.11 or 3.12 (as listed in the PRD)
- Docker Desktop / Docker Compose for the local PostgreSQL, Redis, and Kafka services
- A PostgreSQL client such as `psql` to apply SQL migrations from the host
- M-Pesa Daraja sandbox credentials and a reachable callback URL to exercise the payment flow
- A configured OIDC issuer only when exercising bearer authentication

There is no frontend package manifest or Dockerfile in this repository. Docker Compose supplies the three infrastructure services, not the Python API or a frontend.

## 10. Local Development Setup

The following commands use PowerShell on Windows. Do not use production credentials for local development.

1. Clone and enter the repository:

   ```powershell
   git clone <repository-url>
   cd KodiLegder
   ```

2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -3.12 -m venv venv
   .\venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in local values. `app/core/config.py` also requires `SYSTEM_DATABASE_URL`, which is not currently listed in `.env.example`; configure it separately. The application and system URLs must use the appropriate database roles described in [docs/SECURITY.md](docs/SECURITY.md). Configure M-Pesa values for payment testing. OIDC settings are needed for real bearer-token validation.

   ```powershell
   Copy-Item .env.example .env
   ```

4. Start local infrastructure. Docker Compose reads `POSTGRES_PASSWORD` from `.env`:

   ```powershell
   docker compose up -d postgres redis kafka
   ```

5. Provision the database roles required by the migrations, then apply `db/migrations/*.sql` in numeric order using `psql` against the local PostgreSQL service (`localhost:5434`, database `kodiflow_db`). There is no migration runner configured in this repository. In particular, the `kodiflow_app` role must exist before migrations that grant or revoke its privileges. Review the database and security documentation before applying migrations; do not apply them to a production database as part of local setup.

6. Start the API from the repository root:

   ```powershell
   .\venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

7. Verify the root route at `http://127.0.0.1:8000/`; it returns an online status response. FastAPI's OpenAPI UI is available at `http://127.0.0.1:8000/docs`.

## 11. Environment Configuration

Settings are loaded from environment variables and `.env` by Pydantic Settings. The names below are defined by [app/core/config.py](app/core/config.py); values are intentionally omitted.

| Group | Settings |
| --- | --- |
| PostgreSQL | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`, `DATABASE_URL`, `SYSTEM_DATABASE_URL` |
| Redis | `REDIS_URL`, `RATE_LIMIT_STK_PUSH_REQUESTS`, `RATE_LIMIT_STK_PUSH_WINDOW_SECONDS` |
| M-Pesa | `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`, `MPESA_SHORTCODE`, `MPESA_BASE_URL`, `MPESA_CALLBACK_URL`, `MPESA_CALLBACK_TOKEN`, `MPESA_CALLBACK_ALLOWED_IPS` |
| OIDC | `OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, `OIDC_SIGNING_ALGORITHMS`, `OIDC_JWKS_TIMEOUT_SECONDS` |
| Application/API | `PROJECT_NAME`, `ENVIRONMENT`, `DEBUG`, `CORS_ALLOWED_ORIGINS` |
| Kafka | `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_PAYMENT_TOPIC` |

`DATABASE_URL` is used by ordinary application sessions. `SYSTEM_DATABASE_URL` creates a separate privileged session used by webhook and system workflows. Do not share the system credential with ordinary user requests. `.env.example` contains placeholders, not production values.

In `development` and `test`, source-IP filtering is skipped for local testing. Outside those environments, STK initiation requires an HTTPS `MPESA_CALLBACK_URL` and `MPESA_CALLBACK_TOKEN` of at least 32 characters. KodiLedger appends the token to the configured callback URL as a `token` query parameter and checks it on receipt. Keep it secret, use a long random value, and configure proxy/access logs to omit or redact the query string. The route also enforces `MPESA_CALLBACK_ALLOWED_IPS`, whose default is Safaricom's published callback IP list; verify and maintain that list with Safaricom. The endpoint checks the ASGI peer address and does not use `X-Forwarded-For`; if running behind a proxy, configure the ASGI server to trust only the actual proxy so the peer address cannot be spoofed. Verify in the Daraja sandbox that its callback delivery preserves the query parameter before enabling this flow in production.

## 12. Database

PostgreSQL is the primary database. Numbered SQL files in [db/migrations/](db/migrations/) define the schema; they are applied in filename order with a PostgreSQL client because no migration framework/runner is configured. The schema covers rental/property records, invoices, webhook and payment processing, allocations, credits, ledger entries, outbox events, and the new `app_users` / `user_memberships` identity foundation.

Normal application and system database sessions use separate URLs and roles. RLS policies are defined in migrations 0010 and 0011. Authenticated-to-RLS integration covers selected user-scoped business routes; route and deployment-role coverage remains incomplete. Read [docs/auth.md](docs/auth.md), [docs/DATABASE.md](docs/DATABASE.md), and [docs/SECURITY.md](docs/SECURITY.md) before working with database roles or migrations.

## 13. Running the Tests

Run from the repository root with the project virtual environment:

```powershell
$env:DEBUG = 'false'
.\venv\Scripts\python.exe -m pytest -q
```

Focused suites:

```powershell
$env:DEBUG = 'false'
.\venv\Scripts\python.exe -m pytest -q app/Tests/security
.\venv\Scripts\python.exe -m pytest -q app/Tests/integration
```

Integration tests may require the configured PostgreSQL and Redis services; Kafka-related tests may require Kafka. Some database integration tests use `SYSTEM_DATABASE_URL`, so use a dedicated disposable test database. Security tests include mocked identity and RLS-context checks plus PostgreSQL-backed RLS isolation tests. Pytest configuration is in [pytest.ini](pytest.ini); see [docs/TESTING.md](docs/TESTING.md) for current test setup and commands.

## 14. API

The current FastAPI routes registered in `app/main.py` are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Basic online status |
| `POST` | `/api/v1/payments/stk-push` | Initiate an M-Pesa STK Push; initiation is not payment confirmation |
| `POST` | `/api/v1/webhooks/mpesa` | Receive an M-Pesa callback |
| `GET` | `/api/v1/bff/landlord/me` | Authenticated landlord context and property count |
| `GET` | `/api/v1/bff/caretaker/me` | Authenticated caretaker context |

These are the implemented route groups, not a complete property-management API. OpenAPI documentation is served by FastAPI at `/docs` when the API is running; [docs/API.md](docs/API.md) records the current API contract.

## 15. Development Workflow

```text
Change -> focused tests -> relevant integration tests -> full suite -> review -> commit
```

Financial workflow changes need integration and concurrency coverage because correctness depends on PostgreSQL constraints and transactional behavior. Security and API changes should verify authorization at the route and resource boundary, not only in isolated helpers.

## 16. Documentation Map

| Document | Purpose |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture and component responsibilities |
| [DOMAIN.md](DOMAIN.md) | Implemented business concepts, financial invariants, and unresolved domain decisions |
| [DATABASE.md](DATABASE.md) | Database connections, schema, constraints, and data relationships |
| [auth.md](auth.md) | Authentication, authorization, role/scope rules, and current route matrix |
| [SECURITY.md](SECURITY.md) | Security controls, status, and known gaps |
| [API.md](API.md) | Implemented HTTP API contracts and behavior |
| [TESTING.md](TESTING.md) | Local test commands and integration-test setup |
| [decisions.md](decisions.md) | Accepted technical decisions and conditions for revisiting them |
| [PRD.md](PRD.md) | Product requirements and roadmap |
| [README.md](README.md) | Documentation index |

`docs/DEVELOPMENT.md` and `docs/DEPLOYMENT.md` are not present in this repository.

## 17. Roadmap

The current Phase 3 security work extends the implemented provider-token verification, trusted local identity lookup, selected route RBAC, and transaction-local RLS integration toward a complete identity lifecycle, broad resource ownership enforcement, and verified database-role configuration. PostgreSQL cross-landlord isolation tests exist, but route and deployment coverage still need extension. Later product work includes stable core API contracts, frontend integration, notification flows, and reliability/production hardening as described in the PRD and architecture documents. These are not represented as completed features here.

## 18. Important Engineering Invariants

- PostgreSQL is the source of truth for financial state; Redis is not.
- STK Push initiation is not proof of payment completion; confirmation arrives asynchronously.
- Duplicate payment receipts must not create duplicate financial effects.
- Related financial writes must remain transactionally consistent.
- Tenant isolation requires both application authorization and database controls; current end-to-end enforcement still needs proof.
- Secrets and provider credentials stay server-side and out of source control.
- Outbox consumers must tolerate duplicate event delivery.
