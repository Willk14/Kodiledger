# KodiLedger Technical Requirements

This document records the technical baseline for developing the KodiLedger application and its planned web frontend. It describes current backend behavior separately from frontend and deployment requirements. It does not replace the endpoint-level contract in [API.md](API.md), the identity rules in [auth.md](auth.md), or the database details in [DATABASE.md](DATABASE.md).

## 1. Status and scope

| Area | Current status |
|---|---|
| Backend | FastAPI, Python, SQLAlchemy async, and PostgreSQL migrations are present. |
| Supabase PostgreSQL | The application is configured to use PostgreSQL-compatible connections and RLS. Deployment-specific role and policy behavior must be verified in the target Supabase project. |
| Authentication | OIDC bearer-token verification and local KodiLedger membership lookup are implemented for selected routes. Login, account provisioning, and membership selection are not implemented by the backend. |
| Frontend | No frontend source or package manifest is currently present. The documented target is Next.js, React, TypeScript, with a responsive/PWA-capable experience. |
| CI | The workflow has a dedicated PostgreSQL RLS test database. The ordinary application database on port 5434 has previously failed to connect in CI; verify its provisioning and rerun the checks before treating the branch as merge-ready. |

This document is a baseline for frontend implementation, not a claim that all listed deployment requirements have already been satisfied.

## 2. System architecture

The current system boundary is:

```text
Browser frontend (planned)
        |
        | HTTPS / JSON, OIDC bearer token
        v
FastAPI API
        |
        +-- SQLAlchemy async / asyncpg --> PostgreSQL / Supabase
        |                                    financial source of truth
        +-- Redis -------------------------> rate limits and coordination
        +-- M-Pesa Daraja -----------------> STK initiation and callbacks
        +-- PostgreSQL outbox --> worker --> Kafka
```

PostgreSQL is authoritative for payments, allocations, credits, invoices, ledger entries, reconciliation state, and outbox records. Redis supports coordination, rate limiting, and fast-path idempotency; it is not financial truth. Kafka is downstream event infrastructure and is not part of synchronous financial authority.

The backend has separate application and system PostgreSQL connections. User-scoped business requests use the application connection and transaction-local RLS context. Provider callbacks, selected operator operations, and workers use the system connection. Frontend code must never receive or use the system database credential.

## 3. Backend technology and database requirements

- The API is FastAPI/Python and validates HTTP input with Pydantic schemas.
- Persistence uses SQLAlchemy asynchronous sessions and PostgreSQL through `asyncpg`.
- Ordered SQL files under `db/migrations/` define the database schema and policy changes. Apply migrations through the documented deployment/test process; do not rely on SQLAlchemy model metadata alone to create production schema.
- Supabase connections must use TLS as configured by the environment. Keep application and system database URLs separate.
- Preserve PostgreSQL `NUMERIC`/Python `Decimal` semantics for money. Financial writes that form one workflow must remain in a single PostgreSQL transaction.
- PostgreSQL constraints and locking are part of correctness: receipt uniqueness, allocation/credit constraints, transaction row locks, `ON CONFLICT`, and outbox claim locking must not be bypassed by frontend behavior.
- RLS supplements API authorization. Business routes must continue to set transaction-local scope from the verified local membership and apply resource ownership filters.
- Redis or Kafka outages must not make those systems the authority for whether money was received or allocated.

## 4. Frontend baseline requirements

When the frontend is added:

- Use Next.js, React, and TypeScript, with strict types and a responsive layout usable on mobile and desktop.
- Keep API DTOs and API client code separate from page/presentation components. Use the FastAPI routes and schemas as the contract; do not access PostgreSQL or Supabase tables directly from browser code.
- Configure the API origin through a public frontend environment variable such as `NEXT_PUBLIC_API_BASE_URL`. Do not hard-code deployment hosts.
- Use the approved public identity-provider client configuration only. Never put database credentials, M-Pesa secrets, OIDC signing secrets, or Supabase service-role keys in frontend bundles.
- Attach the current OIDC access token to protected API requests as `Authorization: Bearer <token>`. Follow the identity provider's session lifecycle; do not print tokens, persist them in ad hoc application storage, or use token role claims for authorization.
- Implement explicit loading, empty, validation, unauthorized, forbidden, not-found, conflict, unavailable, and unexpected-error states.
- Make forms keyboard accessible, label inputs, expose validation errors, and avoid relying on color alone for status.
- Format timestamps for display while preserving the API's ISO timestamp values. Display monetary amounts without binary floating-point conversion.
- Do not make product workflows appear available when their backend route does not exist or is not authorized for that role.

## 5. Identity, roles, and ownership

For protected routes, the backend verifies the OIDC token and resolves its `(issuer, subject)` to an active local `app_users` record and exactly one active `user_memberships` record. The backend's local membership supplies the role and tenant/landlord scope. Token claims, browser state, URL parameters, request bodies, and form values do not establish ownership.

Current route access is summarized below; each route's registered dependency remains authoritative:

| Role | Current frontend-relevant access |
|---|---|
| `LANDLORD` | Landlord context, property reads, unit reads/create/update, tenant reads/create, invoice reads/create, payment/allocation/credit reads, ledger reads, and unassigned-payment review/resolution where the route permission allows. |
| `CARETAKER` | Caretaker context, unit reads, and tenant reads. No current invoice, payment, or ledger route is granted. |
| `TENANT` | Tenant self-read and payment/allocation/credit reads scoped to the tenant and landlord. No tenant invoice self-service route is implemented. |
| `ADMIN` | Operator STK unresolved queue and provider status query. This is not landlord-scoped financial access. |
| `SYSTEM` | Trusted internal workflows only; not a normal bearer-user role. |

The backend does not implement signup-to-membership provisioning or membership switching. A frontend must display a clear setup/access state if login succeeds but the identity has no valid local membership. Do not invent an account onboarding or role-switch endpoint.

## 6. Current API capabilities and limitations

The registered user-facing routes are under `/api/v1`:

| Domain | Current operations |
|---|---|
| Landlord context | `GET /bff/landlord/me`; `GET /bff/caretaker/me` for caretaker context. |
| Properties | `GET /properties`, `GET /properties/{property_id}`. No property create/update/delete routes. |
| Units | `GET /properties/{property_id}/units`, `POST /properties/{property_id}/units`, `GET /units/{unit_id}`, `PATCH /units/{unit_id}`. No unit delete route. |
| Tenants | `GET /tenants`, `GET /tenants/{tenant_id}`, `POST /tenants`, `GET /tenants/me`. No tenant update/deactivation/delete route. |
| Invoices | `GET /invoices`, `GET /invoices/{invoice_id}`, `POST /invoices`. No invoice update/delete route and no tenant self-service invoice route. |
| Payments | `GET /payments`, `GET /payments/{payment_id}`, `GET /payments/{payment_id}/allocations`, `GET /payments/{payment_id}/credits`. These are scoped read routes. |
| Unassigned payments | `GET /unassigned-payments`, `POST /unassigned-payments/{payment_id}/resolve`. Resolution accepts a tenant ID; the server selects the tenant's unit/invoice and applies the existing allocation/credit workflow. |
| Ledger | `GET /ledger`, `GET /ledger/{entry_id}`. Read-only; collection supports bounded offset pagination and documented filters. |
| STK Push | `POST /payments/stk-push` exists, but currently has no user authentication or RBAC. Do not expose it in an end-user frontend until this security gap is fixed and the contract is reviewed. |

There is no generic allocation CRUD API, no general pagination convention for all collections, and no dashboard aggregate endpoint. Do not fabricate routes, data, CRUD affordances, or financial status transitions. Consult [API.md](API.md) for exact request/response fields and status behavior.

## 7. API data and error handling

- IDs are UUID strings.
- Money is represented by JSON Decimal strings. Never parse money into JavaScript `number` for arithmetic; use decimal-safe handling or preserve strings until a decimal library is used.
- Date-only values and timestamps are ISO-formatted strings. Preserve date-only values as dates and timestamps with their timezone information.
- List responses are endpoint-specific: most current collection routes return arrays; ledger and operator STK queue return `{items, total, limit, offset}` pages.
- Responses are endpoint-specific JSON; there is no universal success envelope.
- Typical errors use `{"detail": ...}`. Validation errors use FastAPI's `detail` array. Handle by HTTP status and structured response shape, not by matching internal exception text.
- Protected requests may return 401 for missing/invalid identity, 403 for disallowed role/permission or invalid membership context, 404 for missing/out-of-scope resources, 409 for conflicts, 422 for request validation, and 500/502/503 for server or dependency failures where documented.
- Unassigned-payment resolution has deterministic conflict behavior for already-resolved records and repeated commands; it does not promise an idempotent replay response. There is no API-wide idempotency-key convention.
- `GET /` is a shallow process response, not a database/dependency readiness probe.

## 8. Financial workflow requirements

The authoritative payment flow is asynchronous:

```text
STK request accepted
    -> provider callback
    -> webhook persistence and receipt claim
    -> reconciliation
    -> allocation and/or payment credit
    -> invoice state, ledger, and outbox updates
    -> PostgreSQL commit
    -> asynchronous outbox publication to Kafka
```

Requirements:

1. STK acceptance is not payment completion; only the callback/reconciliation workflow confirms payment.
2. PostgreSQL state, not a frontend callback, Redis entry, or Kafka event, determines financial status.
3. The existing allocation engine owns allocation, remaining-balance, and credit behavior. Do not implement allocation arithmetic in the browser.
4. The client cannot choose or override landlord scope, payment amount/status, allocation amount/status, invoice ownership, ledger values, or outbox contents.
5. Ledger history is read-only through the public API. Do not add client-side reversal/deletion behavior.
6. Show pending/initiated payment state distinctly from callback-confirmed and reconciled state. Never present an STK initiation response as proof that payment succeeded.

## 9. Security, browser access, and deployment

- Production browser/API traffic must use HTTPS.
- Configure `CORS_ALLOWED_ORIGINS` for the explicit frontend origins. CORS is browser policy, not authentication or authorization.
- Do not expose PostgreSQL directly to the browser. Do not use a Supabase service-role key in frontend code.
- Keep the API's system connection private to backend operations.
- If using a reverse proxy or TLS termination proxy, it is optional infrastructure, not a prerequisite for local frontend development. Restrict the API origin so traffic cannot bypass intended edge controls, and configure Uvicorn to trust forwarded headers only from the known proxy.
- M-Pesa callback IP validation currently sees the ASGI peer and does not trust arbitrary `X-Forwarded-For`. If deployed behind a proxy, configure the trusted-proxy chain and source-IP handling deliberately; verify provider callbacks end to end before production.
- Use hosting-provider ingress/load balancer or Nginx/Caddy/Traefik as appropriate to the deployment. This document does not require a specific proxy product.
- Never commit `.env`, `.env.rls-test`, access tokens, credentials, or generated environment-specific configuration.

## 10. Test and release requirements

Before a frontend/API integration release:

- Backend CI must run unit, security, PostgreSQL RLS, and relevant integration tests with the required services provisioned.
- Frontend checks must include type checking, linting, and tests for API client auth/error handling, role-gated navigation, form validation, empty states, and protected-route behavior.
- Exercise at least one landlord, caretaker, and tenant session against the API and verify both allowed access and cross-scope denial.
- Verify that failed/expired auth, missing membership, unavailable API, validation failure, and conflict responses produce understandable UI states.
- Verify migration application and RLS role behavior in a disposable test database; a passing unit suite alone does not prove deployed Supabase RLS configuration.
- Run `git diff --check` and ensure generated bundles, local secrets, and environment files are excluded from commits.

## 11. Frontend MVP acceptance criteria

The frontend MVP may be considered contract-compatible when:

- It uses only currently registered API routes and their declared schemas.
- Authentication uses the OIDC access token and backend-resolved membership; no role or ownership is inferred from browser-supplied values.
- UI navigation/actions match the authenticated role and current route permissions.
- Money values are handled without floating-point arithmetic.
- Financial state is read from the API and never invented or mutated in the browser.
- Unsupported operations are clearly unavailable rather than simulated.
- Loading, empty, error, validation, conflict, and membership-setup states are implemented.
- The backend security/CI status and remaining limitations are documented before release.

## 12. Related references

- [Application flows](APP_FLOW.md)
- [API contract](API.md)
- [Authentication and authorization](auth.md)
- [Security posture](SECURITY.md)
- [Database schema and migrations](DATABASE.md)
- [Architecture](ARCHITECTURE.md)
- [Testing guide](TESTING.md)
