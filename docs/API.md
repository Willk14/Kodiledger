# KodiLedger API

This document is the developer-facing contract for the current KodiLedger FastAPI backend and the planned API surface. It is intended to become the stable reference for frontend/backend integration. **IMPLEMENTED** describes behavior present in registered routes and their dependencies; **PARTIAL** means a workflow or security foundation exists but has material gaps; **PLANNED** is not a usable API contract.

The source of truth for the current surface is the running FastAPI application's routes, schemas, and dependencies. Update this document alongside implementation and generated OpenAPI. See [architecture](ARCHITECTURE.md), [security](SECURITY.md), and [product requirements](PRD.md) for deeper design context.

## 1. API Principles

- **IMPLEMENTED:** HTTP routes are under `/api/v1` except the root health response. JSON request validation uses Pydantic. The API layer delegates payment callbacks and STK initiation to services.
- **PARTIAL:** OIDC bearer authentication and database-backed membership authorization protect selected BFF and business routes. User-scoped business routes use transaction-local landlord RLS context. STK initiation, provider callbacks, and admin status operations use separate trust boundaries; see [auth.md](auth.md).
- **PARTIAL:** PostgreSQL is authoritative for payment processing and financial records. Callback processing uses a transaction and receipt uniqueness; Redis is a coordination/rate-limit layer.
- **LEDGER exception:** `GET /api/v1/ledger` supports bounded offset pagination and documented filters. Other collection routes do not yet share a general pagination/filter convention. There is no standard idempotency-key header or uniform error envelope.

## 2. Base URL and Versioning

The registered version prefix is `/api/v1`; deployment host and scheme are environment-specific. Breaking changes should use a new prefix (for example `/api/v2`) and retain the old version during a migration window where feasible. No `/api/v2` exists today.

## 3. Authentication

**IMPLEMENTED on protected routes:** send `Authorization: Bearer <OIDC access token>`. KodiLedger verifies a signed JWT using the configured issuer, audience, JWKS endpoint, and explicit asymmetric algorithm allowlist (`RS256` by default; configured values are restricted to asymmetric algorithms). Required claims are `iss`, `sub`, `aud`, `exp`, and `iat`; signature, expiry, issuer, audience, and issued-at are checked. Issuer and JWKS URLs must use HTTPS. For the complete route matrix and system/provider exceptions, see [auth.md](auth.md).

The verified `(iss, sub)` is resolved to an active local `app_users` record and exactly one active membership. Role and scope claims supplied by the token are ignored. KodiLedger does not issue login tokens; identity provider login/token issuance is external. No credential or live OIDC values belong in this document.

For protected routes, missing/invalid bearer credentials return 401 and include `WWW-Authenticate: Bearer`. An unlinked identity is also treated as 401. Inactive, missing, unsupported, system, or ambiguous membership context is denied with 403. Missing/unsafe OIDC configuration, unavailable JWKS provider, or authentication database errors return 503.

## 4. Authorization and Roles

The code defines `LANDLORD`, `CARETAKER`, `TENANT`, `ADMIN`, and `SYSTEM`. The first four represent application roles; `SYSTEM` is reserved for trusted internal processing and cannot authenticate through a bearer request. Role permission definitions do not imply that an API route exists.

| Role | Current API route access | Scope resolution |
|---|---|---|
| LANDLORD | Landlord context, property, unit, tenant, invoice, payment/allocation/credit read, ledger, and unassigned-payment routes, subject to each route's permission | Active membership's landlord ID; resource queries are constrained by ownership filters and PostgreSQL RLS |
| CARETAKER | `/api/v1/bff/caretaker/me`; unit and tenant reads (`UNIT_READ` / `TENANT_READ`) | Active membership's landlord ID; resource queries are constrained by ownership filters and PostgreSQL RLS |
| TENANT | `GET /api/v1/tenants/me` requires `TENANT_READ`; no invoice route currently | Active membership's tenant and landlord IDs; tenant query is constrained by both values and PostgreSQL RLS |
| ADMIN | STK unresolved request queue and status query require `PAYMENT_READ` | Membership must have no landlord or tenant scope; these routes use the trusted system DB session |
| SYSTEM | No bearer route; used through trusted system DB dependencies | Internal trusted workflow only |

Wrong role or permission returns 403. Client-supplied role or landlord IDs are not authentication authority. Broader route-by-route ownership enforcement remains incomplete.

## 5. Common Request Conventions

**IMPLEMENTED:** JSON bodies use `Content-Type: application/json`; protected routes use the Bearer authorization header. CORS allows `Authorization`, `Content-Type`, and `Idempotency-Key`, but allowing a header in CORS does not mean a route processes it.

There is no API-wide pagination, filtering, sorting, or general idempotency-key convention. The ledger collection has a route-specific bounded offset page; the STK request rejects extra JSON fields, while callback schemas ignore unknown fields to tolerate provider payload extensions.

## 6. Common Response Conventions

Responses are JSON. Successful response shapes are endpoint-specific; there is no shared envelope. FastAPI/Pydantic request validation uses HTTP 422 with a `detail` array. FastAPI `HTTPException` responses use `{"detail": ...}`. The webhook's provider-style `ResultCode` is a body field and is independent of HTTP status.

Invoice creation returns 201. Other no-content responses are not currently used; conflict and not-found behavior is endpoint-specific.

## 7. Error Model

| Condition | Current status/body |
|---|---|
| Request schema validation | 422; FastAPI `{"detail": [{...}]}` validation items |
| Missing/invalid bearer on protected route | 401; `{"detail": "..."}` and Bearer challenge header |
| Membership/role/permission denied | 403; `{"detail": "..."}` |
| OIDC configuration/provider/identity DB unavailable | 503; generic authentication-unavailable detail |
| STK input rejected by service | 400; `{"detail": "..."}` |
| STK upstream/service runtime failure | 502; `{"detail": "..."}` |
| Unexpected STK initiation failure | 500; generic detail |
| STK per-IP limit exceeded | 429; `{"detail": "STK Push rate limit exceeded. Try again later."}` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0` |
| Unknown route/method | FastAPI default 404/405 response |
| Handled webhook processing failure | HTTP 200 with `ResultCode: 1` and a `ResultDesc` string |

Error formats are not fully uniform. In particular, clients must not treat webhook HTTP 200 as proof that internal payment processing succeeded. A consistent sanitized error contract is a follow-up task.

## 8. Health / System Endpoints

| Method and path | Status | Response | Authentication |
|---|---:|---|---|
| `GET /` | 200 | `{"status":"online","system":"KodiFlow Backend Engine"}` | None |

This is a shallow process response, not a database/dependency readiness probe. FastAPI also exposes `/docs`, `/redoc`, and `/openapi.json` using its defaults.

## 9. Landlord API

### IMPLEMENTED

`GET /api/v1/bff/landlord/me` requires a valid Bearer token, `LANDLORD` role, `PROPERTY_READ`, and an active landlord membership. It returns the authenticated principal context and a count of properties in that principal's landlord scope. `user_id` and `landlord_id` are UUIDs; `role` is the `LANDLORD` role; `property_count` is a nonnegative integer. The request uses the normal application database session and transaction-local RLS context; the service/repository query also filters by the verified landlord ID.

```json
{
  "user_id": "<local-user-id>",
  "role": "LANDLORD",
  "landlord_id": "<landlord-id>",
  "property_count": 2
}
```

The response is validated by `LandlordContextRead`. Errors: 401 for missing/invalid bearer credentials, 403 for missing/invalid landlord membership or permission, 503 for authentication dependency failures, and 500 for unexpected database/server failures. The endpoint has no request body or path parameter; extra query values such as `landlord_id` and `role` do not change the authenticated scope. There are no landlord CRUD endpoints in this contract.

### IMPLEMENTED — caretaker context

`GET /api/v1/bff/caretaker/me` requires a valid Bearer token, the `CARETAKER` role, and `UNIT_READ`. It returns the authenticated membership context without reading business rows or opening a database session. The landlord scope is sourced from the verified local membership; query parameters cannot override it.

| Method and path | Success | Errors |
|---|---|---|
| `GET /api/v1/bff/caretaker/me` | 200, JSON object containing `user_id`, `role`, and `landlord_id` (all strings) | 401 for missing/invalid bearer credentials; 403 for a missing/invalid caretaker membership or permission |

There are no caretaker CRUD endpoints. Caretaker unit and tenant reads are documented under the Unit and Tenant APIs; the context endpoint does not itself grant resource access.

## 10. Property API

**IMPLEMENTED:** property reads are available to authenticated landlords. Both routes require `LANDLORD` plus `PROPERTY_READ`; the landlord scope comes from the verified active membership, never a client parameter. They use the normal application database session with transaction-local RLS context. Responses expose only fields defined by the property model for client use.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/properties` | List the current landlord's properties | 200, array of property objects (empty array if none) | 401, 403, 500, 503 |
| `GET /api/v1/properties/{property_id}` | Read one property in the current landlord's scope | 200, property object | 401, 403, 404, 422, 500, 503 |

Property object fields: `id` (UUID), `name`, `county`, `town_location` (string or null), `total_units` (integer), and `created_at` (timestamp or null). List order is by `created_at`, then `id`, ascending. A property outside the caller's scope is indistinguishable from a missing property and returns 404. No create, update, deactivate, or delete route is currently implemented.

## 11. Unit API

### IMPLEMENTED — landlord and caretaker unit reads; landlord unit management

Unit reads are scoped to the authenticated membership's landlord and use the ordinary application database session with transaction-local RLS context. Landlords and caretakers with `UNIT_READ` may list and read units. Only landlords with `UNIT_WRITE` may create or update them. The API never accepts `landlord_id`; creation derives it from the principal and verifies that the parent property belongs to that landlord. A foreign or missing property/unit returns 404.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/properties/{property_id}/units` | List units in a landlord-scoped property, ordered by unit number then ID | 200, array of unit objects (empty if none) | 401, 403, 404, 422 |
| `POST /api/v1/properties/{property_id}/units` | Create a unit under a landlord-scoped property | 201, unit object | 401, 403, 404, 409, 422 |
| `GET /api/v1/units/{unit_id}` | Read a landlord-scoped unit | 200, unit object | 401, 403, 404, 422 |
| `PATCH /api/v1/units/{unit_id}` | Update unit number or rent/fee rates; omitted fields are unchanged | 200, unit object | 401, 403, 404, 409, 422 |

Create fields: `unit_number` (trimmed, 1–50 characters), `base_rent` (nonnegative Decimal with at most 2 decimal places), and optional `garbage_fee`, `security_fee`, and `water_rate_per_unit` (each defaults to `0.00`, nonnegative Decimal with at most 2 decimal places). Update accepts the same fields, all optional, and requires at least one field. Unknown fields and explicit null values are rejected. Duplicate unit numbers within a property return 409. Creating a unit increments the property's `total_units` in the same transaction; creation serializes on the parent property row so the count remains correct under concurrent requests.

Unit responses expose `id`, `property_id`, `unit_number`, `base_rent`, `garbage_fee`, `security_fee`, `water_rate_per_unit`, `is_occupied`, and `created_at`. Financial values remain Decimal/NUMERIC. `landlord_id` is not exposed or accepted. `is_occupied` is read-only; tenant/occupancy lifecycle APIs are not yet implemented. Units have no delete/deactivation operation in this contract.

## 12. Tenant API

### IMPLEMENTED — landlord/caretaker reads, landlord create, and tenant self-read

All tenant routes use the normal application database session with authenticated RLS context. Landlord and caretaker list/detail operations use the membership landlord scope; a tenant cannot use those endpoints. `GET /api/v1/tenants/me` uses the tenant and landlord IDs from the verified membership, never request parameters. An out-of-scope record returns 404.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/tenants` | List tenants in the current landlord scope, ordered by creation time then ID | 200, array of tenant objects | 401, 403, 500, 503 |
| `GET /api/v1/tenants/{tenant_id}` | Read a tenant in the current landlord scope | 200, tenant object | 401, 403, 404, 422, 500, 503 |
| `POST /api/v1/tenants` | Create a tenant under a unit in the current landlord scope | 201, tenant object | 401, 403, 404, 422, 500, 503 |
| `GET /api/v1/tenants/me` | Read the tenant record resolved from authenticated membership | 200, tenant object | 401, 403, 404, 500, 503 |

Create accepts `unit_id` (UUID), `full_name` (trimmed, 1–255 characters), `primary_phone` (`254` followed by 9 digits), optional `id_number` (up to 50 characters), `lease_start_date` (date), and `deposit_amount` (nonnegative Decimal, defaults to `0.00`, at most 2 decimal places). Unknown fields are rejected. Landlord scope, active status, and tenant ID are server-derived. The unit must belong to the caller's landlord. Creating a tenant does not change `Unit.is_occupied`; occupancy lifecycle is separate. The existing schema allows multiple tenant records per unit, so the endpoint does not impose a single-tenant rule.

Tenant responses expose `id`, `unit_id`, `full_name`, `primary_phone`, `lease_start_date`, `deposit_amount`, `is_active`, and `created_at`. Government ID number and landlord ID are not returned. List includes active and inactive historical records. Tenant update, unit reassignment, deactivation, and delete operations are not part of this contract.

## 13. Invoice API

### IMPLEMENTED — landlord list, detail, and create

All Invoice API routes require an authenticated `LANDLORD` membership and use the normal application database session with RLS context. The landlord scope comes from the verified membership; a client-supplied `landlord_id` is rejected. Caretakers and tenants have no Invoice API route in this contract. Tenant self-service invoice reads remain PLANNED.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/invoices` | List invoices in the current landlord scope, ordered by billing month, creation time, then ID | 200, array of invoice objects | 401, 403, 500, 503 |
| `GET /api/v1/invoices/{invoice_id}` | Read an invoice in the current landlord scope | 200, invoice object | 401, 403, 404, 422, 500, 503 |
| `POST /api/v1/invoices` | Create an invoice for a tenant and that tenant's unit | 201, invoice object | 401, 403, 404, 409, 422, 500, 503 |

Create accepts `unit_id`, `tenant_id`, `invoice_number` (trimmed, 1–100 characters), `billing_month` (date), `rent_amount` (required), optional `water_amount`, `garbage_amount`, and `security_amount` (default `0.00`), and `due_date`. Monetary inputs are nonnegative Decimal values with at most two decimal places. Unknown fields are rejected. `landlord_id` is derived from authenticated membership. The unit must belong to that landlord, and the tenant must belong to that landlord and the specified unit; a mismatch returns 404. Duplicate globally unique invoice numbers return 409. Client input cannot set `total_amount` or `is_paid`; the generated `total_amount` is computed by PostgreSQL, and new invoices remain unpaid.

Invoice responses expose `id`, `unit_id`, `tenant_id`, `invoice_number`, `billing_month`, component amounts, generated `total_amount`, `due_date`, `is_paid`, and `created_at`. Decimal values serialize as JSON strings. `landlord_id` is not returned. Payment allocation/reconciliation may change payment state through its existing internal workflow; it is not part of these Invoice routes. Invoice update, mark-paid, cancellation/delete, tenant self-read, payment allocation, reversal, and ledger mutation routes remain PLANNED. Finalized financial records do not have unrestricted update/delete operations.

## 14. Payment API

### IMPLEMENTED — initiate STK Push

`POST /api/v1/payments/stk-push` accepts JSON and returns HTTP 200 when the initiation service returns a mapping. This route has **no user authentication or RBAC dependency**. It is limited by caller IP through Redis, with defaults of 5 requests per 60 seconds; both are configurable.

Accepted requests with Daraja merchant and checkout IDs are recorded in `stk_push_requests` for later status lookup. Recording happens after the external STK request is accepted; a database failure in that window can leave the provider request untracked.

### IMPLEMENTED — operator STK status query

`GET /api/v1/payments/stk-push/unresolved?limit=50&offset=0` requires a platform administrator and returns a paginated queue of STK requests in `PENDING`, `QUERY_ACCEPTED`, or `SUCCEEDED` state that have not received a callback. Each item includes its checkout ID, current status, query count, creation time, and last query time. The default page size is 50 and the maximum is 100. The response does not include raw provider data or payer details.

`POST /api/v1/payments/stk-push/{checkout_request_id}/query` requires an authenticated platform administrator. The checkout ID must belong to an STK request recorded by this API. The API sends Daraja's STK Push Query request and stores the response and query timestamp/count. A provider response code of zero with a final result code is recorded as `SUCCEEDED` or `FAILED`; an accepted but non-final query remains `QUERY_ACCEPTED`. Requests with a received callback return HTTP 409 because the callback workflow already owns reconciliation. Unknown checkout IDs return 404; Daraja failures return a sanitized HTTP 502.

This endpoint reports provider status and does not create payment, allocation, credit, or ledger rows. The query response does not provide the callback's full payment metadata in a form this API can safely reconcile, so confirmed financial effects continue through the callback path. Older STK requests initiated before request tracking was deployed cannot be queried through this endpoint.

Request fields are exact and extra fields are rejected:

| Field | Type and constraint |
|---|---|
| `phone_number` | string, exactly 12 characters, `254` followed by 9 digits |
| `amount` | integer greater than zero |

```json
{"phone_number":"254798765432","amount":150}
```

Response fields are strings (the route converts absent provider fields to empty strings):

```json
{
  "MerchantRequestID": "...",
  "CheckoutRequestID": "...",
  "ResponseCode": "...",
  "ResponseDescription": "...",
  "CustomerMessage": "..."
}
```

Possible errors: 422 schema validation, 429 rate limit, 400 service `ValueError`, 502 `RuntimeError`, and 500 unexpected failure. No idempotency key is accepted or enforced by this route. A successful HTTP response means an STK request was initiated; it does **not** mean payment is confirmed, reconciled, allocated, or credited. Confirmation arrives through the M-Pesa callback below.

Manual payment creation and payment reversal endpoints are not registered. The unassigned-payment assignment endpoint is documented below.

### IMPLEMENTED — landlord and tenant transaction history

Payment history routes require `PAYMENT_READ` and use the normal application database session with RLS. Landlords are scoped by authenticated landlord membership. Tenants are scoped by both authenticated tenant and landlord IDs. Caretaker history remains PLANNED until the API can enforce assigned-unit scope; the role permission by itself does not grant access through these routes. Only transactions linked to a tenant are returned; unassigned-payment review uses the separate assignment workflow below.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/payments` | List tenant-linked payment transactions in the caller's scope, newest first | 200, array of payment objects | 401, 403, 500, 503 |
| `GET /api/v1/payments/{payment_id}` | Read a tenant-linked payment transaction in the caller's scope | 200, payment object | 401, 403, 404, 422, 500, 503 |

Payment history responses expose `id`, `tenant_id`, `mpesa_receipt_number`, `amount`, `payment_method`, `status`, `created_at`, and `completed_at`. `landlord_id`, payer phone/name, provider request IDs, and raw webhook data are not returned. Amounts serialize as Decimal strings. Payment state is read-only here; these routes do not initiate payments, allocate funds, reverse transactions, create credits, or mutate ledger/outbox data.

Allocation and payment-credit detail routes also require `PAYMENT_READ` and first verify that the payment transaction is visible in the caller's scope. Landlords use their membership landlord ID; tenant principals must match both the payment tenant and landlord IDs. Out-of-scope transactions return 404. The routes expose persisted allocation/credit rows only and do not change their state.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/payments/{payment_id}/allocations` | List invoice allocation rows for a visible payment | 200, array of allocation objects (empty if none) | 401, 403, 404, 422, 500, 503 |
| `GET /api/v1/payments/{payment_id}/credits` | List payment-credit rows created from a visible payment | 200, array of credit objects (empty if none) | 401, 403, 404, 422, 500, 503 |

Allocation objects expose `id`, `payment_transaction_id`, `invoice_id`, `amount`, `status`, `created_at`, and `reversed_at`; allocation states are `ALLOCATED` and `REVERSED`. Credit objects expose `id`, `payment_transaction_id`, `tenant_id`, `amount`, `status`, `created_at`, and `applied_at`; credit states are `AVAILABLE`, `APPLIED`, `REFUNDED`, and `CANCELLED`. Monetary values serialize as Decimal strings. These endpoints are read-only. There is no generic `POST /api/v1/allocations`, `GET /api/v1/allocations`, or `GET /api/v1/allocations/{allocation_id}` route. Allocation writes are part of the existing unassigned-payment resolution command below; the API does not expose `InvoiceAllocationService` directly or let a caller select an arbitrary payment/invoice pair.

## 15. M-Pesa Webhook API

### PARTIAL — external callback with request correlation and source IP filtering

`POST /api/v1/webhooks/mpesa` is intended for M-Pesa's STK callback. Outside `development` and `test`, the route requires `MPESA_CALLBACK_TOKEN` (at least 32 characters) as a `token` query parameter and checks the ASGI peer IP against the comma-separated `MPESA_CALLBACK_ALLOWED_IPS` setting before processing. STK initiation requires an HTTPS `MPESA_CALLBACK_URL`; the client adds the token to that URL. The default IP list is based on Safaricom's published callback IP list and should be verified with Safaricom before production use. The route does not trust `X-Forwarded-For`. If deployed behind a proxy, configure the ASGI server to trust only that proxy when deriving the client address. The application also requires the merchant and checkout IDs to match an STK request recorded from an initiation response before persisting the callback. These are shared-secret and network controls; the callback is not provider-signed.

Body shape:

```json
{
  "Body": {
    "stkCallback": {
      "MerchantRequestID": "...",
      "CheckoutRequestID": "...",
      "ResultCode": 0,
      "ResultDesc": "Success",
      "CallbackMetadata": {
        "Item": [
          {"Name": "MpesaReceiptNumber", "Value": "ABC123"},
          {"Name": "Amount", "Value": 150},
          {"Name": "PhoneNumber", "Value": 254798765432}
        ]
      }
    }
  }
}
```

`MerchantRequestID`, `CheckoutRequestID`, `ResultCode`, and `ResultDesc` are required. `CallbackMetadata` is optional in the schema; a successful (`ResultCode == 0`) payment needs receipt, positive amount, and phone metadata or processing fails. Extra keys are ignored at each schema level. Invalid shape returns 422.

Accepted callbacks normally return HTTP 200 with service result JSON. Invalid/missing callback tokens and source IPs outside the configured allowlist return HTTP 403; missing production token configuration, invalid allowlist configuration, or invalid source address return HTTP 503. A callback whose merchant/checkout pair is not recorded returns HTTP 401 before inbox persistence. Provider-declined callbacks are persisted and acknowledged with `ResultCode: 0` and provider result fields. Successful callbacks are resolved to a landlord using configured shortcode, claimed by receipt, reconciled, and committed. Duplicates return `ResultCode: 0` and `ResultDesc: "Duplicate webhook ignored"`. A matched payment may return reconciliation details; an unmatched tenant is recorded as unassigned. Caught internal/validation processing errors roll back and return `ResultCode: 1` with an error-containing description while retaining HTTP 200. This behavior is not a stable/sanitized provider error contract and needs deliberate review.

## 16. Allocation API

**IMPLEMENTED API contract:** allocation reads are payment-scoped through `GET /api/v1/payments/{payment_id}/allocations`; the only public financial allocation command is `POST /api/v1/unassigned-payments/{payment_id}/resolve`. Callback reconciliation and this resolution workflow call the internal allocation service. No generic allocation CRUD routes are registered, and the service is not exposed directly to HTTP callers.

## 17. Unassigned Payment API

**IMPLEMENTED — landlord unassigned-payment review and resolution:** a successful callback is unassigned when reconciliation finds no active tenant matching the payer phone under the callback's landlord scope. The landlord chooses the intended active tenant; the server verifies that tenant is in the same landlord scope and derives its unit. The existing allocator then selects that tenant's oldest unpaid invoice. It applies at most the lesser of payment funds available and the invoice's remaining balance; overpayment becomes a payment credit, which is automatically applied FIFO to further unpaid invoices. If there is no unpaid invoice, the remaining available payment amount becomes a credit. Existing credits are automatically applied FIFO when a new invoice is created. Credit applications are immutable records, invoice paid state reflects both payment allocations and credit applications, and the payment credit read response includes its original `amount` and remaining `available_amount`. Refund and cancellation APIs are not implemented.

Both routes use the normal application session and RLS. They require `LANDLORD` plus `PAYMENT_ASSIGN`. The request accepts only `tenant_id`; unknown fields are rejected. The server derives landlord, authoritative payment amount/status, tenant unit, invoice, allocation, ledger values, and outbox payload from authenticated scope and PostgreSQL records. The list returns unresolved rows only (`is_resolved` false or NULL), with `id`, `mpesa_receipt_number`, `amount`, `payer_phone`, `payer_name`, `invalid_account_reference`, and `created_at`; it omits the internal raw-webhook ID. No pagination, detail route, or generic CRUD is implemented.

The resolver locks the unassigned-payment row, then locks the payment transaction. The existing allocator uses the same payment lock before locking the selected invoice. Webhook reconciliation does not acquire an unassigned-payment lock after acquiring a payment lock. This gives resolution the order unassigned payment → payment transaction → invoice, while other allocation paths use payment transaction → invoice. The resolver attaches the tenant, reuses existing allocation/credit rules, records one full-payment ledger credit and idempotent `PAYMENT_PROCESSED` outbox event, updates processing state when the row is still `UNASSIGNED`, and records the resolving user, unit, and database timestamp. Reconciliation/resolution do not commit independently: allocation, credit, invoice state, ledger, outbox, payment assignment, processing state, and resolution commit in one PostgreSQL transaction; any failure rolls the complete write set back. The outbox application-role access is restricted to SELECT/INSERT of payment-transaction events whose transaction belongs to the current landlord RLS context.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/unassigned-payments` | List unresolved receipts in the authenticated landlord scope | 200, array of unassigned payment objects | 401, 403, 500, 503 |
| `POST /api/v1/unassigned-payments/{payment_id}/resolve` | Resolve a receipt for an active same-landlord tenant and apply normal allocation/credit, ledger, and outbox processing | 200, resolution result with allocation outcome | 401, 403, 404, 409, 422, 500, 503 |

The request body is exactly `{"tenant_id": "<UUID>"}`. `landlord_id`, payment or invoice IDs, amounts, payment/allocation status, unit ownership, ledger values, and outbox state cannot be supplied or overridden by the client. A missing/out-of-scope payment or inactive/out-of-scope tenant returns 404. Already-resolved or inconsistent financial records return 409. Sequential and concurrent repeated resolve requests return one success and deterministic 409 conflict(s); they create no duplicate allocation, credit, ledger entry, or outbox event. There is no generic idempotency-key header or success-response replay. The response schema is `UnassignedPaymentResolutionRead` (`id`, `payment_transaction_id`, `mpesa_receipt_number`, `tenant_id`, `unit_id`, `amount`, `allocation`, `outbox_event_id`, `resolved_at`). Resolution does not guarantee an invoice allocation: the existing allocator may return `UNALLOCATED` when the tenant has no unpaid invoice.

## 18. Ledger API

**IMPLEMENTED — landlord read-only ledger history:** both routes require `LANDLORD` plus `PAYMENT_READ`, use the normal application session with RLS, and constrain every query to the authenticated landlord. A foreign or missing entry returns 404. No ledger mutation or reversal route is exposed.

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/v1/ledger` | List ledger entries in the current landlord scope, newest first | 200, `LedgerEntryPage` | 401, 403, 422, 500 |
| `GET /api/v1/ledger/{entry_id}` | Read one ledger entry in the current landlord scope | 200, `LedgerEntryRead` | 401, 403, 404, 422, 500 |

`GET /ledger` supports `limit` (default 50, maximum 100), `offset` (default 0), and optional exact filters `payment_transaction_id`, `tenant_id`, `invoice_id`, `unit_id`, `property_id`, and `receipt`, plus inclusive `created_from` and `created_to` timestamps. Timestamps must include a timezone offset and `created_from` must not exceed `created_to`. Landlord ID is always derived from the authenticated membership; a `landlord_id` query value is not an authorization filter. Property filtering follows the ledger entry's unit relationship. There are no amount filters or property ID fields in the ledger response.

The page response contains `items`, `total`, `limit`, and `offset`. Rows are ordered by `created_at DESC, id DESC`; offset pages are deterministic for a fixed dataset, but concurrent inserts can shift later pages. Filtering and pagination are evaluated inside the landlord-scoped query and remain subject to RLS.

`LedgerEntryRead` exposes ledger, unit, tenant, invoice, and payment-transaction IDs where present, receipt number, entry type, amount, payment method, status, description, and `created_at`. Payer phone, payer name, merchant request ID, account reference, and landlord ID are omitted. Amounts serialize as Decimal strings. The timestamp is when the ledger row was created, not a provider event-time field.

The schema allows `CREDIT` and `DEBIT` entry types and several payment statuses. Current payment reconciliation and unassigned-payment resolution create a single completed `CREDIT` for the full receipt and link it to the payment transaction; they do not create separate ledger rows for invoice allocation or tenant credit application. `invoice_id` is nullable and these current ledger writers leave it unset. Receipt is unique when non-null. No reversal/correction record workflow is implemented. The API has GET routes only; underlying database policies permit scoped updates, so database-level immutability should not be inferred from the read-only HTTP boundary.

## 19. Webhook / Event Architecture

For matched callback payments, the verified path is: HTTP callback → trusted system PostgreSQL session and transaction → payment reconciliation/ledger and outbox row → separate outbox worker → Kafka publisher. An initially unassigned payment receives the ledger/outbox effects only when resolved through the landlord API. The publisher/worker is background infrastructure, not an HTTP API endpoint. No Kafka consumer implementation is present.

## 20. Idempotency

**IMPLEMENTED in callback processing:** Redis provides a fast-path receipt lock; PostgreSQL's unique receipt claim is authoritative for preventing duplicate financial processing. Payment records and reconciliation effects are coordinated within the PostgreSQL transaction. Outbox event idempotency keys are unique; worker delivery can still repeat across the publish/mark crash window, so downstream consumers would need deduplication.

**IMPLEMENTED for unassigned-payment resolution:** the service locks the unresolved payment and its transaction; once resolved, a repeated command receives HTTP 409. This resource-state check prevents duplicate allocation, credit, ledger, processing, and outbox effects. The API does not claim same-success response replay and does not accept an idempotency-key header.

**NOT IMPLEMENTED:** STK initiation does not accept a client idempotency key. Redis state is not the financial source of truth.

## 21. Financial API Invariants

ACID describes the PostgreSQL transaction boundary; it does not make a multi-system HTTP workflow spanning PostgreSQL, Redis, Safaricom, and Kafka one atomic transaction.

### PostgreSQL transaction guarantees

- **Atomicity:** Unit creation inserts the unit and updates the property's `total_units` in the same transaction. Tenant creation inserts one tenant row. Invoice creation performs its landlord/property/unit/tenant checks and insert in the same request transaction; a duplicate invoice number rolls the insert back and returns 409. These writes commit before a successful response is returned. Failed database writes are rolled back when caught by the service or when the request-scoped session is closed.
- **Consistency:** Pydantic schemas enforce request shape and monetary/date constraints; services enforce ownership and tenant/unit consistency; PostgreSQL constraints enforce keys, foreign keys, uniqueness, payment amount checks, and the generated invoice total. The invoice tenant/unit relationship is validated by the API; the current database schema does not define a composite constraint for that relationship, so any non-API writer must enforce the same rule.
- **Isolation:** PostgreSQL's configured default isolation is used (normally `READ COMMITTED`); the API does not promise serializable execution or a snapshot spanning multiple requests. Unit creation locks the parent property while counting and inserting. Unique database constraints arbitrate duplicate invoice numbers and M-Pesa receipts under concurrency.
- **Durability:** A successful database-backed mutation response is sent only after PostgreSQL reports a commit. Survival of host/storage failures still depends on the deployed PostgreSQL durability configuration and backups, which are outside this API contract.

The callback inbox row commits first so the provider payload survives a process crash or a later reconciliation rollback. Financial processing then runs in one PostgreSQL transaction: receipt claim, normalized transaction, allocation/credit or unassigned-payment record, ledger effects when matched, processing state, inbox completion, and matched-payment outbox row commit together or roll back together. Failed-provider callbacks are recorded and marked complete without creating a successful payment transaction. Allocation serializes by locking the tenant with `FOR NO KEY UPDATE`, then the payment transaction, then the selected invoice. It reads committed allocation and credit totals while holding those locks; persisted payment amount less allocations and credits is the available payment balance. The tenant lock remains compatible with the key-share lock a concurrent payment insert takes for its tenant foreign key, avoiding a lock-upgrade deadlock while still serializing tenant financial writers. When no unpaid invoice exists, the allocator records the remaining available payment amount as a tenant payment credit without creating an invoice allocation. Failed successful-payment callbacks remain pending for the webhook replay worker, which claims rows with `SKIP LOCKED`, recovers stale claims, retries with capped backoff, and retains the last error; after ten failed attempts the row is left for operator review. The outbox row is atomic with the financial effects, but Kafka publishing happens after commit and may be delivered more than once; downstream consumers must deduplicate. A database rollback cannot undo an external payment already executed by Safaricom.

STK Push is an external initiation call, not a PostgreSQL transaction. HTTP 200 means the provider initiation returned successfully; it does not mean the payment completed or that any database financial effect committed. The callback is the source of confirmed payment state. On callback processing failures, the route returns HTTP 200 with `ResultCode: 1`, while the committed inbox record is retained for internal replay. Run `python -m app.workers.webhook_replay` alongside the API to process pending callbacks; callbacks that exhaust ten attempts remain stored with their last error for operator review.

Payment history, invoice reads, and other GET routes do not mutate financial state. Read isolation is per database statement; a later request may observe newer committed data.

Verified callback workflow behavior includes PostgreSQL receipt claims preventing duplicate processing, partial allocation, excess payment credits, unassigned-payment handling, and Decimal/NUMERIC financial values. Integration tests cover duplicates, concurrency, partial/exact/overpayment behavior, unassigned receipts, rollback, and outbox effects. Payment confirmation depends on callback reconciliation, not STK initiation acceptance.

## 22. Ownership and RLS

Protected landlord flow: verified OIDC identity → unique active local membership → role/permission check → trusted principal values bound as transaction-local PostgreSQL RLS settings → service/repository query scoped to that landlord. The landlord `/me` property count filters by the principal landlord ID and is also subject to RLS.

**PARTIAL:** PostgreSQL RLS policies and a `get_rls_db` dependency exist. The landlord `/me`, property, unit, tenant, invoice, and payment history routes consume `get_rls_db`; PostgreSQL integration tests verify cross-landlord isolation, role-limited writes, tenant self-read scope, and invoice/payment ownership. The caretaker `/me` route returns membership context but reads no database rows. STK initiation has no user scope; webhook processing uses a separate privileged system session. Do not infer that every application route or financial resource is protected by RLS. See [security documentation](SECURITY.md) for database-role and policy limitations.

## 23. Pagination, Filtering and Search

**PARTIAL:** `GET /api/v1/ledger` implements route-specific offset pagination and exact filters documented in the Ledger API section. Other collections do not have shared pagination, filtering, sorting, or search conventions. Do not assume the ledger query parameters apply elsewhere.

## 24. OpenAPI

FastAPI generates `/openapi.json` from registered routes, Pydantic request/response models, metadata, and dependencies. `/docs` and `/redoc` render that schema. This Markdown explains current behavior and planned gaps; it is not a manually authored OpenAPI specification. Keep `API.md`, implementation, and OpenAPI output aligned, and verify the generated path list when routes change.

## 25. Current vs Target API Surface

| Domain | Current | Target | Notes |
|---|---|---|---|
| Authentication | IMPLEMENTED foundation | Stable identity integration | External OIDC issuance; membership controls local role/scope |
| Landlord | IMPLEMENTED `/bff/landlord/me` | Landlord workflows | No CRUD |
| Caretaker | IMPLEMENTED `/bff/caretaker/me`; scoped unit and tenant reads | Caretaker workflows | No writes or assigned-unit scope model |
| Properties | PARTIAL landlord list/read | Create/update/deactivate if specified | List/get use authenticated landlord scope and RLS; mutations have no route |
| Units | IMPLEMENTED landlord/caretaker reads; landlord create/update | Unit list/detail/create/update | Scoped through property and landlord; create updates the property's unit count |
| Tenants | IMPLEMENTED scoped list/detail/create and tenant self-read | Tenant management and self-service | Landlord/caretaker reads and landlord create use RLS; tenant self-read is membership scoped |
| Invoices | IMPLEMENTED landlord list/read/create | Invoice list/detail/create; tenant self-read and lifecycle mutations | Landlord-scoped with RLS; total is database-generated; create verifies tenant/unit ownership |
| Payments | IMPLEMENTED STK Push initiation, admin status query, and landlord/tenant transaction reads | Payment history and explicit business actions | STK initiation remains unauthenticated; history is scope-filtered; query does not reconcile financial effects |
| Allocations and payment credits | IMPLEMENTED scoped reads; financial writes are internal to reconciliation/resolution | `GET /payments/{payment_id}/allocations`, `GET /payments/{payment_id}/credits` | `PAYMENT_READ`, payment ownership check, and RLS |
| Unassigned payments | IMPLEMENTED landlord review and resolution command | `GET /unassigned-payments`, `POST /unassigned-payments/{payment_id}/resolve` | `LANDLORD` + `PAYMENT_ASSIGN`, active same-landlord tenant, RLS; atomic financial write set |
| Ledger | IMPLEMENTED landlord-scoped reads; writes remain internal | `GET /ledger`, `GET /ledger/{entry_id}` | `PAYMENT_READ`, landlord scope, and RLS; no mutation route |
| Webhooks | PARTIAL M-Pesa callback | Authenticated/validated provider integration | No sender authentication currently visible |

## 26. Frontend Integration Rules

Use a frontend API client/service between UI components and FastAPI. Attach Bearer tokens only to protected endpoints. Handle 401 by refreshing/re-authenticating according to the identity provider flow; handle 403 as an authorization denial; show field-level 422 validation details; honor `Retry-After` on STK 429. Do not retry STK initiation blindly because this API has no idempotency key.

Payment transaction history is available to landlords and tenants through the scoped read routes. STK initiation itself does not create a transaction record, so there is no endpoint to resolve an initiation request while its callback is pending. Provider-declined callbacks, reconciliation details, and internal callback failures are not exposed as a user-facing status API today.

## 27. API Stability Rules

Avoid breaking changes where possible; version breaking contracts; preserve financial semantics and callback idempotency; keep error behavior explicit; update request/response schemas, this document, and generated OpenAPI together; update relevant security/integration tests when a contract changes. Do not silently make finalized financial data freely mutable.

## 28. API Security Rules

Never expose secrets or trust client role/landlord identifiers as authority. Enforce backend authorization and ownership for every future resource route. Sensitive payment records need scoped access. Add appropriate authenticity verification before treating external callbacks as trusted. Return only identifiers and financial data needed by the caller. Financial records require explicit auditable business operations, not unrestricted mutation. STK initiation currently lacks user auth; treat that as a known gap and protect abuse with its existing per-IP limit until a suitable caller contract is implemented.

## 29. API Testing

Tests under `app/Tests/security/` cover OIDC verification, identity/membership resolution, authorization, BFF and scoped business-route access, RLS context, PostgreSQL RLS isolation, and webhook-service rollback behavior. `app/Tests/integration/` covers STK rate limiting, webhook persistence/idempotency, unassigned payments, concurrent callbacks and invoice allocation, partial/exact/overpayment behavior, and outbox worker/publisher cases. These are test cases in the repository; their presence does not imply every deployment runs them. Contracts remain incomplete for the planned domains and payment business actions.

## 30. API Roadmap

| Stage | State |
|---|---|
| External authentication and local identity resolution | IMPLEMENTED foundation |
| Role/permission checks | IMPLEMENTED foundation; only selected routes enforce them |
| PostgreSQL RLS | IMPLEMENTED foundation; integration with public routes is PARTIAL |
| API contract reference | PARTIAL; this document establishes the current reference |
| Landlord/property APIs | PARTIAL: context and property list/read implemented; mutations and broader workflows remain PLANNED |
| Caretaker APIs | PLANNED beyond context endpoint |
| Tenant/invoice/payment read and business APIs | PARTIAL: tenant, invoice, and assigned payment reads implemented; broader workflows remain PLANNED |
| Allocation/unassigned payment/ledger APIs | PLANNED public routes; callback capabilities are PARTIAL |
| Frontend integration | PLANNED against concrete route contracts |

## Current implementation gaps

- STK initiation has no user authentication or idempotency key.
- M-Pesa callback checks currently comprise source-IP filtering and exact STK request correlation; Daraja callbacks are not cryptographically authenticated, production ingress/proxy configuration is deployment-owned, and caught processing failures use HTTP 200.
- The property list/read routes and landlord context use the authenticated PostgreSQL RLS dependency; broad ownership enforcement is not complete.
- Tenant membership resolution supports only exactly one active membership; membership selection is unavailable.
- STK status query provides provider status only; payment reconciliation still depends on callback metadata.
- The API error model and provider callback response behavior need a stable, sanitized contract before wider integration.
