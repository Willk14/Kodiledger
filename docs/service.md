# KodiLedger Application Services

This document summarizes the Python modules in `app/services/`. These classes coordinate application rules between FastAPI endpoints, repositories, PostgreSQL, Redis, and external providers. Repositories handle database queries; API routes handle HTTP validation, authorization dependencies, response formatting, and request-level commits where applicable.

## Domain and query services

| Service | Responsibility |
|---|---|
| [`LandlordService`](../app/services/landlord_service.py) | Provides landlord context data, including the count of properties in the authenticated landlord's scope. |
| [`PropertyQueryService`](../app/services/property_query_service.py) | Lists and retrieves properties for a landlord. It is read-only. |
| [`UnitService`](../app/services/unit_service.py) | Lists and retrieves landlord-scoped units, creates units, updates unit fields, and translates database uniqueness conflicts into a domain conflict. Unit creation also updates the parent property's unit count in the repository transaction. |
| [`TenantService`](../app/services/tenant_service.py) | Lists and retrieves tenants by landlord, resolves a tenant from authenticated membership context, and creates tenants under a landlord-owned unit. |
| [`InvoiceService`](../app/services/invoice_service.py) | Lists and retrieves landlord-scoped invoices. On creation it verifies that the unit and tenant belong together in the landlord's scope, creates the invoice, and applies available tenant credits to eligible invoices in the caller's transaction. |
| [`InvoiceAllocationService`](../app/services/invoice_allocation_service.py) | Applies persisted payment funds to the oldest eligible unpaid invoices, records excess funds as tenant payment credits, and applies available credits FIFO when invoices are created. It locks tenant/payment/invoice rows in a defined order and never commits; the caller owns the transaction. |
| [`LedgerQueryService`](../app/services/ledger_query_service.py) | Reads landlord-scoped ledger entries, including the supported ledger filters and pagination. It does not create or change ledger entries. |
| [`PaymentQueryService`](../app/services/payment_query_service.py) | Lists and retrieves payment transactions within landlord or tenant scope. |
| [`PaymentFinancialQueryService`](../app/services/payment_financial_query_service.py) | Reads invoice allocations and payment credits for a payment after its ownership and visibility are established. |
| [`UnassignedPaymentResolutionService`](../app/services/unassigned_payment_resolution_service.py) | Lists unresolved landlord-scoped receipts and resolves a receipt to an eligible same-landlord tenant. Resolution reuses the allocation service and coordinates assignment, allocation/credit, ledger, processing state, and outbox writes in the caller's transaction. |

## Payments, callbacks, and events

| Service | Responsibility |
|---|---|
| [`PaymentInitiationService`](../app/services/payment_initiation_service.py) | Calls the M-Pesa integration to initiate an STK Push or query its status. Provider calls are external side effects and cannot participate in a PostgreSQL transaction. |
| [`WebhookService`](../app/services/webhook_service.py) | Validates and stores M-Pesa callback inbox records, applies Redis receipt locking as a fast path, handles duplicate callbacks, and delegates successful-payment processing to reconciliation. PostgreSQL uniqueness is the authoritative duplicate guard. |
| [`ReconciliationService`](../app/services/reconciliation_service.py) | Converts a confirmed callback into a normalized payment and coordinates tenant matching, allocation or credit, ledger effects, processing state, and an outbox event. The caller supplies and commits the PostgreSQL transaction. |
| [`IdempotencyService`](../app/services/idempotency_service.py) | Acquires and releases short-lived Redis receipt locks to reduce duplicate callback work. If Redis is unavailable it fails open; PostgreSQL remains authoritative for idempotency. |
| [`OutboxEventService`](../app/services/outbox_event_service.py) | Builds and inserts durable payment-processed events in PostgreSQL. The event row is part of the caller's transaction so it commits or rolls back with the financial changes. |
| [`EventPublisher`](../app/services/event_publisher.py) | Defines the asynchronous interface for publishing one event or a batch. Production Kafka and logging publishers are in `app/integrations/events/`. |
| [`OutboxWorker`](../app/services/outbox_worker.py) | Claims pending outbox rows, publishes them through an `EventPublisher`, records success or failure, and schedules retries. Publishing is after the financial transaction commits and can be delivered more than once. |
| [`WebhookReplayWorker`](../app/services/webhook_replay_worker.py) | Claims callback inbox rows that need retry, re-runs reconciliation, and records bounded backoff and terminal operator-review state. |
| [`TestEventPublisher`](../app/services/test_event_publisher.py) | In-memory event publisher used by integration tests; it is not a production event transport. |

## Runtime processes

FastAPI endpoints use the domain services in-process. The standalone worker entry points in [`app/workers/`](../app/workers/) run the outbox publisher and webhook replay loop as separate long-lived processes. For staging, deploy the API and the two workers as separate Render services so worker retries continue independently of web requests.

See [`API.md`](API.md) for route contracts and database transaction boundaries, [`ARCHITECTURE.md`](ARCHITECTURE.md) for system design, and [`SECURITY.md`](SECURITY.md) for authentication, authorization, and row-level security details.
