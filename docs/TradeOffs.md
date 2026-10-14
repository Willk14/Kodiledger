# KodiLedger Design Trade-Offs

This document explains the main trade-offs visible in the current backend. It
describes what each choice optimizes for, what it costs, and the limits that
should be considered before changing it. It complements [ARCHITECTURE.md](ARCHITECTURE.md),
[decisions.md](decisions.md), [DOMAIN.md](DOMAIN.md), and [SECURITY.md](SECURITY.md).

## Architecture and code organization

| Choice | Optimizes for | Cost or limitation |
|---|---|---|
| Separate HTTP controllers, application services, repositories, and models | Clear boundaries: HTTP concerns stay out of business workflows, and persistence queries stay out of route handlers. | More modules and indirection than a small single-file API; contributors must follow the boundaries and avoid duplicating rules across layers. |
| FastAPI with asynchronous SQLAlchemy sessions | Handling concurrent network and database waits without dedicating a blocked thread to every request. | Async code adds lifecycle and debugging complexity. Blocking work inside an async request or worker can still stall the event loop. |
| Explicit request/response schemas | Validated inputs and stable public response shapes instead of returning database models directly. | Schema changes require deliberate mapping and documentation updates; not every internal model field is automatically exposed. |
| A deliberately limited, implemented API surface | Preserving a coherent contract and keeping financial commands narrowly controlled. | Some product workflows and generic CRUD operations are not available yet; clients may need to wait for explicit APIs rather than perform arbitrary operations. |

## Financial correctness and data flow

| Choice | Optimizes for | Cost or limitation |
|---|---|---|
| PostgreSQL is the authority for financial state | Durable constraints, transactions, unique claims, and row locks protect payments, allocations, credits, ledger rows, and outbox intent. | Database availability and transaction/lock performance are on the critical path. Contended payment or invoice rows can make requests wait. |
| Allocation uses PostgreSQL row locks in a consistent payment-then-invoice order | Prevents concurrent workflows from spending the same payment balance or over-allocating an invoice; consistent order reduces deadlock risk. | Serializes conflicting operations and requires every new writer to respect the established lock order. |
| One ledger credit records the full payment receipt; allocations and credits describe how funds are applied | Keeps the received amount auditable and separates receipt from invoice settlement. | Consumers must not interpret the full ledger credit as the amount paid toward a particular invoice; they must use allocation and credit records too. |
| Excess or currently unapplied funds are kept as tenant credits and applied FIFO to unpaid invoices | Preserves payment value and applies older obligations first without asking a client to choose internal financial values. | Landlords cannot choose an arbitrary invoice through the current API. Refunds, reversals, and manual reallocation are not implemented. |
| Unmatched tenant payments are recorded as unassigned and resolved through one landlord command | Preserves valid receipts while requiring a scoped human decision before linking them to a tenant; reuses the same allocation/ledger workflow. | Resolution is an additional operational step. A retry after resolution returns a conflict rather than replaying the original success response. |
| Raw callbacks are committed to an inbox before financial reconciliation | A process crash during reconciliation does not erase the provider callback; a worker can retry from durable data. | Inbox persistence and financial processing are separate transactions, so an inbox row can temporarily remain pending or require operator review. |
| STK initiation and payment confirmation are separate stages | The API does not treat a provider's request-accepted response as proof that money was paid; confirmed outcomes come from later callbacks/status handling. | Payment completion is asynchronous and depends on provider callback delivery, correlation, and retry processing. A PostgreSQL rollback cannot undo a provider request already sent. |

## Coordination and events

| Choice | Optimizes for | Cost or limitation |
|---|---|---|
| Redis handles rate limiting and short-lived receipt locks, while PostgreSQL remains the correctness boundary | Fast distributed coordination without making cache state the financial record. PostgreSQL uniqueness protects against duplicate financial effects if the Redis lock is lost. | Redis adds an operational dependency. STK rate limiting fails when Redis operations fail; idempotency locking is a best-effort fast path and may proceed when Redis is unavailable. |
| Transactional outbox rows are written with financial changes; a worker publishes them after commit | Financial state and durable intent to publish commit atomically, without putting Kafka availability inside the payment transaction. | Publishing is asynchronous and at least once: a crash after Kafka accepts an event but before PostgreSQL marks it published can cause a duplicate. Consumers must deduplicate. |
| Outbox delivery uses a separate worker and Kafka publisher abstraction | Worker failures/retries are isolated from web request handling; the publisher can be substituted in tests. | Requires a broker, worker deployment, monitoring, and consumer-side idempotency. A Kafka consumer is not currently implemented in this repository. |
| Callback replay and outbox workers poll PostgreSQL on intervals | Straightforward recovery and deployment as independent processes, with bounded retry state persisted in PostgreSQL. | Polling adds database queries and retry latency; it is less immediate than push-based queues and requires careful multi-worker claim/lease handling. |

## Security and identity

| Choice | Optimizes for | Cost or limitation |
|---|---|---|
| Verify an OIDC token, then resolve its issuer/subject to a local active membership | Keeps KodiLedger roles and tenant/landlord scope under local control instead of trusting client-provided scope or role claims. | Users need local account/membership provisioning, and issuer/audience/JWKS settings must match the identity provider. The full login and provisioning lifecycle is not complete. |
| Combine route authorization with transaction-local PostgreSQL RLS for scoped business requests | Provides both application-level permission checks and a database isolation backstop. | Role grants, RLS policies, transaction context, and route coverage must stay aligned. Coverage is partial and must not be assumed for unprotected routes. |
| Keep separate `kodiflow_app` and `kodiflow_system` database sessions | Limits ordinary user requests to the application role while trusted callback/worker flows use a distinct role and explicit system policies. | More credentials and configuration are required. The system role has broad trusted workflow access and must be protected as a high-impact secret. |
| Protect callbacks with a shared token, source-IP checks, and initiated-request correlation | Rejects callbacks that lack configured controls or do not match a KodiLedger-created STK request. | This is not provider-signed authentication. A token in the callback URL can leak through logs if not redacted; provider IP lists can change; proxy address handling must be configured carefully. |
| Authentication is applied to selected routes rather than globally | Allows incremental migration of route groups while authentication integration is developed. | Unprotected routes need deliberate review before exposure; passing authentication tests for selected routes does not prove complete API authorization. |

## Operations and deployment

| Choice | Optimizes for | Cost or limitation |
|---|---|---|
| Ordered SQL migration files are applied manually with PostgreSQL tools | Explicit, reviewable SQL and portability without adding a migration framework during active schema work. | No automatic migration history/runner is configured. Operators must apply files in order, stop on errors, and verify the target environment carefully. |
| Settings come from environment variables or an ignored local `.env` file | Keeps secrets out of source code and makes local and hosted configuration explicit. | Required settings must be supplied in each environment; URL-encoded credentials and provider-specific values can be error-prone to configure. |
| M-Pesa defaults to the Daraja sandbox URL | Makes development and staging safer by default. | A production integration requires an explicit, reviewed provider configuration and production credentials; sandbox success does not validate production callbacks or settlement behavior. |
| API and workers are separate processes | Lets web traffic and background retry/publishing workloads scale and fail independently. | Each process needs compatible configuration, deployment, logs, and health/alerting; a healthy API does not prove its workers are running. |

## Revisit triggers

Reassess these choices when the system adds refunds or reversals, manual allocation,
additional callback providers, a complete account lifecycle, broader route
authorization, event consumers, high-volume queueing needs, or automated migration
management. Preserve the financial invariants and update the related design record
when a trade-off changes.
