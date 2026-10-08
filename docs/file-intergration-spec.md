# KodiLedger file integration specification

This document describes how the FastAPI backend and Next.js frontend integrate. The backend and frontend are separate repositories with separate Git histories.

## Repository responsibilities

- `kodiledger-backend/` owns the HTTP API, OIDC token verification, membership and role resolution, authorization, data access, and response schemas.
- `kodiledger-frontend/kodiledger-frontend/` owns the browser interface, Supabase sign-in/session handling, typed API client, validation, and display components.
- The frontend must not connect to a database or make ownership decisions. Backend authorization and scoping remain authoritative.

## HTTP and authentication

- Backend routes are mounted under `/api/v1`.
- Frontend `NEXT_PUBLIC_API_BASE_URL` is the backend origin only, with no `/api/v1` suffix and no trailing slash. The frontend API client appends `/api/v1`.
- The frontend obtains the signed-in user's access token from its Supabase client and sends it as `Authorization: Bearer <token>` to protected API routes.
- The backend validates OIDC issuer, audience, expiry, issued-at time, signature, and JWKS key. It resolves `(issuer, subject)` to its local user and active membership. Token role or ownership claims, query parameters, and frontend state do not establish authorization.
- Frontend role discovery probes `GET /bff/landlord/me`, then `GET /bff/caretaker/me`, then `GET /tenants/me`. A 403 or 404 advances to the next probe. There is no unified who-am-I route.
- A Supabase service-role key must never be included in browser code or a `NEXT_PUBLIC_` variable.

## CORS and configuration

Backend deployments must include each frontend origin in `CORS_ALLOWED_ORIGINS` as a comma-separated list. The current backend allows credentials, methods `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, and `OPTIONS`, and headers `Authorization`, `Content-Type`, and `Idempotency-Key`.

Protected backend requests also require backend OIDC configuration: HTTPS issuer URL, audience, HTTPS JWKS URL, and an explicit asymmetric signing algorithm allowlist. The frontend requires these public values in its local environment: `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and `NEXT_PUBLIC_SUPABASE_ANON_KEY`. No secret or live environment value belongs in this document.

## Verified API surface used by the frontend

| Resource/workflow | Routes used | Backend access rule |
| --- | --- | --- |
| Role context | `GET /bff/landlord/me`, `GET /bff/caretaker/me`, `GET /tenants/me` | Each route validates its corresponding active role/context. |
| Properties | `GET /properties`, `GET /properties/{property_id}` | LANDLORD only. |
| Units | `GET /properties/{property_id}/units`, `POST /properties/{property_id}/units`, `GET /units/{unit_id}`, `PATCH /units/{unit_id}` | LANDLORD and CARETAKER read; LANDLORD create/update. |
| Tenants | `GET /tenants`, `GET /tenants/{tenant_id}`, `GET /tenants/me`, `POST /tenants` | LANDLORD and CARETAKER list/detail; TENANT self-read; LANDLORD create. |
| Invoices | `GET /invoices`, `GET /invoices/{invoice_id}`, `POST /invoices` | LANDLORD only. |
| Payments | `GET /payments`, `GET /payments/{payment_id}`, `GET /payments/{payment_id}/allocations`, `GET /payments/{payment_id}/credits` | LANDLORD and TENANT; tenant records are scoped by backend-resolved membership. |
| Unassigned payments | `GET /unassigned-payments`, `POST /unassigned-payments/{payment_id}/resolve` | LANDLORD with payment-assignment permission. |
| Ledger | `GET /ledger`, `GET /ledger/{entry_id}` | LANDLORD with payment-read permission. |

The frontend does not call or expose `POST /payments/stk-push`. It does not call the admin STK queue/query or webhook routes.

## Request and response rules

- Request field names and constraints are represented by frontend `src/lib/api/contract.ts` and the generated TypeScript schema.
- Unit create accepts `unit_number`, `base_rent`, and optional `garbage_fee`, `security_fee`, and `water_rate_per_unit`. Unit patch accepts those fields, requires at least one value, and rejects explicit nulls. Unknown request fields are rejected.
- Tenant create requires `unit_id`, `full_name`, `primary_phone`, and `lease_start_date`; `deposit_amount` and `id_number` are optional. The API does not return the government ID number.
- Invoice create requires `unit_id`, `tenant_id`, `invoice_number`, `billing_month`, `rent_amount`, and `due_date`; component amounts are optional and default to zero. Unknown fields are rejected.
- Unassigned-payment resolution requires `tenant_id`; unknown fields are rejected.
- Monetary values remain decimal strings in frontend request/view-model code and API responses. Formatting must not convert them to JavaScript `number` or perform arithmetic.
- View-model mappers expose only fields selected for presentation. They omit landlord scope, government identifiers, and raw provider/webhook payload fields.
- Ledger pagination uses `limit` (default 50, maximum 100) and `offset` (default 0), returning `{items,total,limit,offset}`. Supported filters: `payment_transaction_id`, `tenant_id`, `invoice_id`, `unit_id`, `property_id`, `receipt`, `created_from`, and `created_to`.
- Collection routes other than ledger and the admin STK queue do not use a shared pagination contract.

## Errors and frontend states

Backend error responses do not have a uniform envelope. Request validation returns 422 with a FastAPI `detail` array. Most HTTP errors return `{"detail": ...}`. The frontend branches on status and presents loading, empty, error, and successful data/form states. It handles 401, 403, 404, 409, 422, 429, 500, 502, and 503. A 429 may include `Retry-After`; the backend documents this for STK initiation, a route the frontend does not use.

Frontend tests cover client behavior, view-model mapping, UI states, and route presence in the checked-in OpenAPI file. They do not establish backend authorization, deployed schema, database, or RLS correctness.

## Contract refresh workflow

1. Review backend route and schema changes in the backend repository.
2. From the frontend working directory, export `app.openapi()` to `contracts/openapi.json` using the backend virtual environment, `PYTHONDONTWRITEBYTECODE=1`, and non-secret placeholder settings. Do not start the FastAPI lifespan or connect to a database.
3. Record the backend commit used in `contracts/SOURCE.txt`.
4. Run `npm run gen:api` in the frontend repository. Do not hand-edit `src/lib/api/generated/schema.d.ts`.
5. Update typed request/response aliases, mappers, explicit resource columns, and fixtures when the contract changes.
6. Run `npm run typecheck`, `npm test`, and `npm run build` from the frontend repository.

## Known integration gaps

- No unified who-am-I endpoint.
- No tenant invoice self-service or caretaker property/payment routes.
- No generic list pagination/filter convention outside the documented exceptions.
- Error details vary by route; `Retry-After` is not a general rate-limit contract.
- This frontend does not use property edit/delete, tenant edit/delete, invoice edit/delete, unit deletion, ledger mutation/reversal, or membership provisioning/switching routes.
