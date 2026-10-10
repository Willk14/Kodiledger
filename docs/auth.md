# KodiLedger Authentication and Authorization

This document describes the implemented authentication and authorization behavior and the boundaries that future routes must preserve. The registered FastAPI routes and their dependencies are the implementation source of truth. [API.md](API.md) lists the HTTP contracts; [SECURITY.md](SECURITY.md) records broader security controls and risks.

## Authentication and identity

### Protected user requests

Protected routes accept an OIDC access token in the HTTP Bearer authorization header:

```http
Authorization: Bearer <access-token>
```

`app/security/authentication.py` verifies the JWT signature using the configured HTTPS JWKS endpoint and an explicit asymmetric algorithm allowlist. It validates issuer, audience, expiry, issued-at time, and required claims `iss`, `sub`, `aud`, `exp`, and `iat`. KodiLedger does not issue tokens or implement hosted login, refresh, or revocation.

After token verification, `app/security/identity.py` resolves the verified `(issuer, subject)` pair to an active `app_users` account and exactly one active `user_memberships` row. KodiLedger takes the user ID, role, landlord ID, and tenant ID from its own records. Role and ownership claims in the token or request do not grant authority.

The identity must have exactly one active membership. No active membership, multiple active memberships, invalid role/scope combinations, or a `SYSTEM` membership cannot be used as a normal bearer identity. Membership provisioning and membership selection are not implemented.

### Authentication outcomes

| Condition | HTTP result |
| --- | --- |
| Missing, malformed, invalid, expired, unknown, or inactive identity | `401` with Bearer challenge |
| No active membership, ambiguous active memberships, unsupported role, or invalid membership scope | `403` |
| Unsafe/missing OIDC configuration, JWKS provider unavailable, or identity database unavailable | `503` |

The exact sanitized detail text is dependency-specific. Clients should branch on status, not on internal exception wording.

## Roles, scope, and permissions

Roles are `LANDLORD`, `CARETAKER`, `TENANT`, `ADMIN`, and `SYSTEM`. Permissions describe actions; FastAPI dependencies combine the required role and permission for each route. Role permissions are defined in `app/security/authorization.py`; the presence of a permission in that matrix does not mean a corresponding route exists.

| Role | Membership scope | Implemented authenticated route access |
| --- | --- | --- |
| `LANDLORD` | One `landlord_id`; no `tenant_id` | Landlord context, property reads, unit reads/writes, tenant list/detail/create, invoice list/detail/create, payment/allocation/credit reads, ledger reads, and unassigned-payment review/resolution as allowed by each route's permission. |
| `CARETAKER` | One `landlord_id`; no `tenant_id` | Caretaker context, unit reads, and tenant list/detail reads. No invoice or payment route is currently granted to this role. |
| `TENANT` | One `landlord_id` and one `tenant_id` | Tenant self-read and payment/allocation/credit reads constrained to that tenant and landlord. No invoice route is currently implemented for tenant self-service. |
| `ADMIN` | No landlord or tenant scope | Platform-operator STK request queue and status-query routes, requiring `PAYMENT_READ`. This does not grant landlord-scoped financial access. |
| `SYSTEM` | Trusted internal processing only | Not accepted as a bearer membership. System workflows use a separate trusted database dependency and role. |

Route permissions include `PROPERTY_READ`, `UNIT_READ`/`UNIT_WRITE`, `TENANT_READ`/`TENANT_WRITE`, `INVOICE_READ`/`INVOICE_WRITE`, `PAYMENT_READ`, and `PAYMENT_ASSIGN`. Review the endpoint dependency before relying on the broader role matrix. An authenticated role alone is not resource authorization.

Out-of-scope resources should be treated as not found where route behavior uses ownership-filtered queries. Client-supplied `landlord_id`, role, or tenant scope is never an authorization source.

## Route trust boundaries

| Route family | Authentication and authorization | Database context |
| --- | --- | --- |
| Landlord, property, unit, tenant, invoice, payment history, allocation/credit read, ledger, and unassigned-payment APIs | OIDC bearer identity; explicit role/permission checks; application scope filters | `get_rls_db` binds authenticated scope and uses the ordinary application session |
| Admin STK unresolved queue and status query | OIDC bearer identity; `ADMIN` plus `PAYMENT_READ` | Trusted system database session; no landlord scope |
| `POST /api/v1/payments/stk-push` | No user bearer authentication or RBAC currently; Redis per-IP rate limit | Trusted system database session to persist initiated request metadata |
| `POST /api/v1/webhooks/mpesa` | Provider callback checks: configured callback token, source-IP allowlist outside development/test, and initiated-request correlation. This is not user OIDC authentication and there is no provider signature verification currently. | Trusted system database session for reconciliation |
| Background workers | No end-user bearer identity | Trusted system database session, narrowly scoped by worker responsibility |

Unauthenticated STK initiation is a known security gap. Before exposing it to end users or public clients, define and enforce an authenticated caller contract and abuse controls. Do not infer authorization from the rate limit.

## PostgreSQL row-level security

Protected business routes that declare `get_rls_db` call `set_rls_context()` on the request-scoped database session. It sets `app.current_landlord_id`, `app.current_user_id`, and `app.current_role` transaction-locally from the resolved principal. Final RLS policies in migrations `0010` and `0011` primarily scope records by landlord; application services and repositories also apply resource-specific tenant and ownership filters. `app.current_role` is set by the helper but is not an authority input to the final policies.

RLS is an additional enforcement layer, not a replacement for route authorization. Routes using the system database session use explicit system-role policies on the tables required by trusted callbacks and workers; they do not use a role-level `BYPASSRLS` attribute. Keep application and system database credentials separate, and restrict the system credential to trusted workflows.

The schema/migration must be installed and provisioned consistently in each environment. The presence of policy SQL alone does not prove a deployed role is constrained correctly. See [DATABASE.md](DATABASE.md) and [SECURITY.md](SECURITY.md) for policy and role details.

## Rules for new endpoints

1. Declare an explicit authenticated principal dependency and the narrowest role/permission combination needed.
2. Derive actor and tenant/landlord scope from the resolved membership. Reject client-supplied scope as authority.
3. Use `get_rls_db` for user-scoped business data; ensure service/repository predicates also enforce the resource relationship.
4. For system/provider operations, use a distinct trust mechanism and system session; do not reuse user roles or accept a bearer role claim as proof.
5. Return `401` for missing/invalid authentication, `403` for authenticated but unauthorized/invalid membership context, and `404` for resources outside the caller's visible scope where appropriate.
6. Add route-level and database-backed cross-scope tests for sensitive changes. Keep test evidence and remaining coverage gaps explicit in [TESTING.md](TESTING.md).

## Document synchronization

- This file is the detailed authentication/authorization behavior reference.
- [API.md](API.md) owns endpoint contracts and links route access back here.
- [SECURITY.md](SECURITY.md) owns security posture, deployment controls, and risks; it should not redefine route permissions differently.
- [ARCHITECTURE.md](ARCHITECTURE.md) owns the request/data flow diagrams.
- [README.md](README.md) carries a short status summary and links here.
- Update these documents in the same change as route dependencies, identity rules, role scope, or RLS behavior.
