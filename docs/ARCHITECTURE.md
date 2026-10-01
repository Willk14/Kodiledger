KodiLedger — System Architecture

Document: ARCHITECTURE.md
Product: KodiLedger
Architecture Status: Active Development
Primary Backend: FastAPI / Python
Primary Database: PostgreSQL 15
Cache & Coordination: Redis
Event Infrastructure: Transactional Outbox + Kafka
Payment Provider: Safaricom M-Pesa Daraja API
Frontend: Next.js / React / TypeScript / PWA
1. Purpose

This document describes how KodiLedger is structured, how its components interact,
where responsibility belongs, and how important financial and reliability guarantees
are achieved.

The architecture is intentionally divided into:

    Presentation

    API

    Application/domain services

    Persistence/repositories

    PostgreSQL

    Redis

    M-Pesa integration

    Transactional outbox

    Kafka/background workers

    Future notification/reconciliation workers

The primary architectural principle is:

    External payment activity is asynchronous, PostgreSQL is authoritative for financial state, Redis provides fast distributed coordination, and durable side effects are emitted through the transactional outbox.

2. High-Level Architecture

                           ┌───────────────────────┐
                           │       USERS           │
                           │                       │
                           │ Landlord              │
                           │ Caretaker             │
                           │ Tenant                │
                           └───────────┬───────────┘
                                       │
                                       ▼
                         ┌────────────────────────────┐
                         │        Next.js / React     │
                         │        PWA Frontend        │
                         │                            │
                         │ Dashboard / Forms / Mobile │
                         └────────────┬───────────────┘
                                      │ HTTPS / JSON
                                      ▼
                         ┌────────────────────────────┐
                         │          FastAPI           │
                         │        API Layer           │
                         │                            │
                         │ Auth / RBAC / Routes       │
                         │ Validation / Dependencies   │
                         └────────────┬───────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │          Application Services       │
                    │                                     │
                    │ Payment Initiation                  │
                    │ Webhook Processing                  │
                    │ Reconciliation                      │
                    │ Invoice Allocation                  │
                    │ Ledger                             │
                    │ Idempotency                        │
                    └──────────────┬───────────┬──────────┘
                                   │           │
                         ┌─────────▼──────┐   ┌▼─────────────┐
                         │ Repositories   │   │ Redis        │
                         │               │   │              │
                         │ PostgreSQL    │   │ Idempotency  │
                         │ persistence   │   │ Locks        │
                         └────────┬──────┘   │ Rate limits  │
                                  │          └──────────────┘
                                  ▼
                         ┌──────────────────┐
                         │   PostgreSQL     │
                         │                  │
                         │ Tenants          │
                         │ Properties       │
                         │ Units            │
                         │ Invoices         │
                         │ Payments         │
                         │ Allocations      │
                         │ Ledger           │
                         │ Webhooks         │
                         │ Outbox Events    │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Outbox Worker    │
                         │                  │
                         │ Claim → Publish  │
                         │ Retry / Backoff  │
                         └────────┬─────────┘
                                  │
                                  ▼
                              ┌───────┐
                              │ Kafka │
                              └───┬───┘
                                  │
                     ┌────────────┼──────────────┐
                     ▼            ▼              ▼
                 Consumers     Analytics      Notifications
                 (future)      (future)       (future)

External payment path:

Safaricom Daraja
       │
       ▼
M-Pesa Webhook Endpoint
       │
       ▼
Webhook Service
       │
       ├── Redis fast-path
       ├── PostgreSQL authoritative claim
       ├── Reconciliation
       ├── Allocation
       ├── Ledger
       └── Outbox

3. Architectural Principles
3.1 PostgreSQL is the financial authority

PostgreSQL is the authoritative source for:

    Payment processing state

    Invoice state

    Allocation

    Payment credits

    Ledger entries

    Reconciliation state

    Outbox records

Redis must never be treated as the financial source of truth.
3.2 Redis is a coordination and performance layer

Redis is used for:

    Fast-path payment idempotency

    Distributed locking around duplicate webhook processing

    STK Push rate limiting

If Redis is unavailable, PostgreSQL must remain capable of protecting financial
correctness through its own constraints and transaction semantics.
3.3 External payments are asynchronous

M-Pesa STK Push initiation and final payment completion are separate events.

STK Push request
      │
      ▼
Daraja accepts request
      │
      ▼
Customer interacts with phone
      │
      ▼
Payment completes/fails
      │
      ▼
Safaricom callback
      │
      ▼
KodiLedger reconciliation

The backend must not mark a payment as finally completed merely because an STK
request was accepted.
3.4 Financial state changes are transactional

For a successful callback, the intended processing boundary is:

Persist webhook
      ↓
Claim payment
      ↓
Reconcile
      ↓
Allocate invoice
      ↓
Update ledger
      ↓
Create outbox event
      ↓
Mark processing state
      ↓
COMMIT

On failure:

Exception
    ↓
ROLLBACK PostgreSQL transaction
    ↓
Release Redis lock when applicable
    ↓
Return safe failure response

This prevents a financial workflow from being partially committed inside one
database transaction.

A database rollback cannot undo an external M-Pesa transaction. Recovery therefore
depends on durable webhook records, idempotency, reconciliation, and future recovery
workers.
4. Layered Backend Architecture

KodiLedger follows a layered structure.

HTTP / API
   ↓
Application Services
   ↓
Repositories / Integrations
   ↓
Infrastructure

4.1 API Layer

Responsibilities:

    HTTP routing

    Request parsing

    Authentication dependencies

    Authorization dependencies

    HTTP response mapping

    Input validation

    Rate-limiting dependencies

The API layer should not contain complex financial logic.

For example:

app/api/v1/endpoints/payments.py

is responsible for receiving an STK Push request and mapping the application
result to an HTTP response.
4.2 Application Service Layer

Responsibilities:

    Business workflow orchestration

    Transaction boundaries

    Domain-level coordination

    Error handling

    Calling repositories

    Calling integration services

Examples:

PaymentInitiationService
WebhookService
ReconciliationService
InvoiceAllocationService
IdempotencyService

Services coordinate operations but should not become SQL dumping grounds.
4.3 Repository Layer

Repositories encapsulate persistence operations.

Examples:

WebhookRepository
LandlordRepository
PaymentProcessingRepository
OutboxEventRepository

Benefits:

    Keeps SQL outside application services.

    Makes integration testing easier.

    Allows persistence details to evolve without rewriting workflows.

    Centralizes important database constraints and queries.

5. Database Architecture

PostgreSQL is the primary persistence layer.

Core conceptual relationship:

Landlord
   │
   ├── Properties
   │       │
   │       └── Units
   │              │
   │              └── Tenant
   │
   ├── Payments
   ├── Invoices
   ├── Ledger
   └── Outbox

Important financial concepts include:

Payment Transaction
       ↓
Invoice Allocation
       ↓
Ledger Entry

Payment > Invoice
       ↓
Payment Credit

6. PostgreSQL Roles and RLS

The implementation uses separate database access contexts:

kodiflow_app
      │
      └── normal application access
          with RLS protections

kodiflow_system
      │
      └── system/webhook/background operations
          with required elevated RLS capability

The application database connection is intentionally separated from the system
connection.

Conceptually:

User-facing application request
        ↓
Application DB session
        ↓
RLS applies

System webhook/background operation
        ↓
System DB session
        ↓
System-level database operations

This separation is important because a single unrestricted database role would
weaken tenant isolation.

The exact authenticated-to-RLS context propagation is a Phase 3 requirement and
must be connected to the future authentication/RBAC implementation.
7. Multi-Tenancy

KodiLedger is designed as a multi-tenant application.

Core records carry landlord/tenant ownership context.

Conceptually:

Landlord A
   ├── Property A
   ├── Unit A1
   └── Tenant A

Landlord B
   ├── Property B
   ├── Unit B1
   └── Tenant B

The system must not allow:

Landlord A
   ↓
Landlord B financial records

The intended defense-in-depth model is:

Authentication
      ↓
Role / tenant context
      ↓
Application authorization
      ↓
PostgreSQL RLS

The database therefore remains a second line of defense rather than relying
entirely on API code.
8. M-Pesa STK Push Architecture

The STK Push initiation path is:

Client
  ↓
POST /api/v1/payments/stk-push
  ↓
Rate limiter
  ↓
PaymentInitiationService
  ↓
MpesaClient
  ↓
OAuth token
  ↓
Daraja STK Push
  ↓
Response to FastAPI
  ↓
Client

The M-Pesa client performs:

    Credential validation

    Phone validation

    Amount validation

    Callback URL validation

    OAuth token acquisition

    OAuth token caching

    HTTP client reuse

    STK Push request construction

    Response parsing

9. Daraja OAuth Caching

The M-Pesa client maintains an in-process OAuth token cache.

Conceptually:

Request 1
   ↓
No valid token
   ↓
Daraja OAuth
   ↓
Cache token

Request 2
   ↓
Valid token exists
   ↓
Reuse token
   ↓
Skip OAuth request

A lock is used around token refresh so concurrent requests do not unnecessarily
refresh the token simultaneously.

Important architectural limitation:

    The current cache is process-local.

If the application later runs multiple worker processes or multiple application
instances, each process will maintain its own OAuth cache unless a shared token
cache is introduced.

This is acceptable for the current development architecture.
10. HTTP Connection Reuse

The M-Pesa integration uses a shared asynchronous HTTP client rather than creating
a completely new client for every request.

Purpose:

    TCP connection reuse

    TLS connection reuse

    Reduced connection setup overhead

    Better latency consistency

Lifecycle management of the shared client should remain explicit in application
startup/shutdown handling before production.
11. M-Pesa Webhook Architecture

The webhook path is intentionally separate from STK Push initiation.

Safaricom
    │
    ▼
POST /api/v1/webhooks/mpesa
    │
    ▼
FastAPI endpoint
    │
    ▼
WebhookService

The webhook service:

    Extracts callback metadata.

    Persists the raw webhook.

    Handles failed M-Pesa transactions.

    Validates successful transactions.

    Resolves the landlord.

    Acquires Redis idempotency protection.

    Claims the payment in PostgreSQL.

    Reconciles the payment.

    Allocates it to an invoice.

    Updates financial state.

    Creates an outbox event.

    Marks processing status.

    Commits the transaction.

12. Dual-Layer Idempotency

KodiLedger intentionally does not rely on Redis alone.

                 Payment Receipt
                       │
                       ▼
              ┌─────────────────┐
              │ Redis fast-path │
              │     lock        │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   PostgreSQL    │
              │ authoritative   │
              │ payment claim   │
              └─────────────────┘

Layer 1 — Redis

Used to quickly detect duplicate/concurrent processing.
Layer 2 — PostgreSQL

Used as the authoritative state boundary.

This protects against the case where Redis:

    Expires

    Restarts

    Becomes unavailable

    Contains stale coordination state

Financial correctness must not depend solely on cache state.
13. Race-Condition Protection

A simplified concurrent scenario:

Webhook A ─────────┐
                   ├── same M-Pesa receipt
Webhook B ─────────┘

Expected behavior:

A → Redis lock / DB claim → process
B → duplicate/concurrent path → do not double-credit

The PostgreSQL claim is the authoritative protection when multiple application
requests arrive concurrently.

The architecture also uses transactional database operations around allocation
and ledger updates.

Concurrency integration tests have exercised scenarios involving two concurrent
payments and the same invoice, including partial allocation and subsequent
overpayment/credit behavior.
14. Invoice Allocation Architecture

Financial allocation is performed by a dedicated service.

Payment
   │
   ▼
Invoice Allocation Service
   │
   ├── exact payment
   ├── partial payment
   └── overpayment

Exact

Payment = Remaining Invoice
        ↓
Invoice paid

Partial

Payment < Remaining Invoice
        ↓
Allocate payment
        ↓
Invoice remains outstanding

Overpayment

Payment > Remaining Invoice
        ↓
Pay remaining invoice
        ↓
Create Payment Credit

These operations remain inside the broader reconciliation transaction.
15. Ledger Architecture

KodiLedger uses an append-oriented financial model rather than treating a
mutable "total paid" field as the ultimate accounting source.

Conceptually:

Payment
   ↓
Ledger event/entry
   ↓
Auditability

Financial adjustments should likewise be represented as explicit ledger events
rather than silently rewriting historical financial values.

This supports:

    Auditability

    Reconciliation

    Reversal handling

    Historical reconstruction

    Financial investigation

The ledger is an accounting model, not simply a dashboard cache.
16. Transaction Boundaries and Rollback

A key transaction should follow:

BEGIN
  │
  ├── webhook persistence
  ├── payment claim
  ├── reconciliation
  ├── invoice allocation
  ├── ledger update
  ├── outbox insertion
  └── processing-state update
  │
COMMIT

If an exception occurs:

ROLLBACK
  │
  ├── Remove database changes from transaction
  └── Release Redis lock when owned

This protects against:

Payment inserted ✅
Invoice allocated ✅
Ledger failed ❌

leaving a partially committed financial transaction.

Instead:

Payment inserted
Invoice allocated
Ledger failed
     ↓
ROLLBACK
     ↓
None of the transaction's database changes remain committed

17. Deadlock Strategy

The architecture should reduce deadlocks through:

    Short transactions

    Consistent lock ordering

    Minimal work while locks are held

    Avoiding unnecessary database locks

    Database-level concurrency tests

    Explicit deadlock testing

Important:

    KodiLedger is not considered mathematically "deadlock-proof" until the final lock order has been reviewed and dedicated deadlock/failure tests pass.

Future code should ensure competing transactions acquire resources in the same
logical order.

The target model is conceptually:

Payment processing
      ↓
Invoice
      ↓
Allocation
      ↓
Ledger
      ↓
Outbox

The actual SQL lock order should be verified whenever new financial workflows
are introduced.
18. Transactional Outbox

Kafka publishing is decoupled from the critical financial transaction through
an outbox.

Instead of:

DB COMMIT
   ↓
Kafka publish

the system does:

BEGIN
   ↓
Financial change
   ↓
Outbox event inserted
   ↓
COMMIT

Then:

Outbox Worker
   ↓
Claim event
   ↓
Publish to Kafka
   ↓
Mark PUBLISHED

This prevents the classic failure:

Database commit ✅
Kafka publish ❌

without a durable record that the event still needs to be published.
19. Outbox Idempotency

Outbox insertion uses an idempotency key.

Conceptually:

INSERT INTO outbox_events (...)
VALUES (...)
ON CONFLICT (idempotency_key)
DO NOTHING;

This prevents multiple identical attempts from creating multiple logical outbox
events for the same idempotency key.
20. Outbox Worker Concurrency

Multiple workers may run simultaneously.

The claim operation is designed so workers do not claim the same event concurrently.

Conceptually:

Worker A ──┐
           ├── pending outbox rows
Worker B ──┘

PostgreSQL row-level locking and:

FOR UPDATE SKIP LOCKED

allow workers to divide work without waiting on rows already claimed by another
worker.

A stale-claim recovery mechanism exists so events do not remain permanently
locked if a worker disappears.
21. Outbox Retry Strategy

When publishing fails:

Attempt 1
   ↓
retry

Attempt 2
   ↓
retry

Attempt 3
   ↓
retry

The worker uses exponential backoff with a cap.

The architecture treats event delivery as at-least-once.

Therefore:

    Kafka consumers must be designed to be idempotent.

The producer uses Kafka producer idempotence to reduce duplicate publication at
the producer level, but consumer-side idempotency is still required for end-to-end
processing guarantees.
22. Rate Limiting

STK Push initiation is protected by a Redis-backed rate limiter.

Conceptually:

Client
   ↓
STK Push endpoint
   ↓
Redis fixed-window limiter
   ↓
Allowed → application
Blocked → HTTP 429

The limiter uses an atomic Redis operation pattern for incrementing a request
counter and establishing its expiration.

The current configuration is intended for development/MVP protection and should
be adjusted for production traffic characteristics.

The webhook endpoint is intentionally treated differently because it is a
provider callback rather than a user-controlled STK Push initiation endpoint.
23. Background Processing

Expensive or failure-prone work should not block critical user-facing requests.

Target background workers include:

Outbox events
Notifications
SMS
WhatsApp
Nightly reconciliation
Report generation
Future analytics

The architecture is intended to allow:

HTTP request
   ↓
fast response

background worker
   ↓
expensive side effect

rather than:

HTTP request
   ↓
send SMS
   ↓
generate PDF
   ↓
publish events
   ↓
wait on external services
   ↓
response

24. Future Notification Architecture

Planned notification path:

Financial event
     ↓
Outbox
     ↓
Kafka
     ↓
Notification consumer
     ↓
SMS / WhatsApp

Notification failures should not corrupt the underlying payment ledger.

Notifications should support:

    Retries

    Backoff

    Failure status

    Observability

    Idempotent delivery handling

25. Future Reconciliation Architecture

The product is expected to include a recovery path for missing/delayed callbacks.

Conceptually:

Safaricom transaction history
             │
             ▼
      Reconciliation Job
             │
             ▼
      Compare against DB
             │
       ┌─────┴─────┐
       │           │
   Already found   Missing
                   │
                   ▼
             Process safely
             through the
             same idempotent
             reconciliation path

The goal is to recover from:

    Dropped callbacks

    Delayed callbacks

    Temporary application/network failures

The recovery process must reuse the same financial integrity rules rather than
writing a second independent accounting path.
26. Frontend Architecture

The frontend is planned as:

Next.js
  +
React
  +
TypeScript
  +
PWA

Primary experiences:

Landlord
   ↓
Executive dashboard

Caretaker
   ↓
Mobile/field operations

Tenant
   ↓
Low-friction browser/payment flows

The frontend should communicate through typed API services.

Conceptually:

FastAPI OpenAPI
      ↓
TypeScript types
      ↓
API client/service layer
      ↓
React components

The frontend should not embed backend accounting logic.
27. Frontend/Backend Parallel Development

Backend and frontend can be developed independently.

Temporary frontend architecture:

UI
 ↓
Service interface
 ↓
Mock implementation

Once backend contracts stabilize:

UI
 ↓
Service interface
 ↓
Real FastAPI implementation

This prevents frontend development from being blocked while backend endpoints are
still being implemented.

The API contract is the boundary between both teams/workstreams.
28. Role-Based Architecture

The intended access model is:

LANDLORD
   │
   ├── Full administrative/property access
   ├── Financial dashboards
   ├── Tenant management
   ├── Payment management
   └── Caretaker management

CARETAKER
   │
   ├── Assigned units
   ├── Occupancy/payment status
   ├── Meter readings
   └── Operational payment logging

TENANT
   │
   ├── Payment interaction
   ├── Invoice/balance views where authorized
   └── Receipt/status flows

The frontend should adapt navigation and UX to these roles.

The backend remains authoritative for authorization.
29. Request Lifecycle
Standard user request

Browser
  ↓
FastAPI route
  ↓
Authentication
  ↓
Authorization
  ↓
Application service
  ↓
Repository
  ↓
PostgreSQL
  ↓
Response

STK Push request

Browser
  ↓
FastAPI
  ↓
Rate limiter
  ↓
PaymentInitiationService
  ↓
MpesaClient
  ↓
Cached OAuth / Daraja
  ↓
Response

M-Pesa callback

Safaricom
  ↓
Webhook endpoint
  ↓
Webhook service
  ↓
Raw webhook persistence
  ↓
Redis idempotency
  ↓
PostgreSQL claim
  ↓
Reconciliation
  ↓
Invoice allocation
  ↓
Ledger
  ↓
Outbox
  ↓
COMMIT

Background event

PostgreSQL
  ↓
Outbox
  ↓
Claim
  ↓
Kafka
  ↓
Consumer

30. Failure Model

KodiLedger assumes failures can occur at every boundary.

Examples:

Browser → API
API → Redis
API → PostgreSQL
API → Daraja
Worker → Kafka
Worker → Notification provider
Network → all external systems

The architecture therefore emphasizes:

    Timeouts

    Retries where safe

    Idempotency

    Transactions

    Durable outbox records

    Failure states

    Audit trails

    Recovery paths

31. What Rollback Protects

Database rollback protects:

Webhook insert
Payment claim
Invoice allocation
Ledger changes
Outbox insertion
Processing status

when they are inside the same database transaction.

Rollback does not protect:

Safaricom payment
Customer M-Pesa wallet
External SMS already sent
External API calls already completed

External side effects therefore require idempotency/reconciliation/compensation
strategies rather than database rollback alone.
32. What Protects Against Race Conditions

KodiLedger uses several layers:

Redis idempotency
        +
PostgreSQL authoritative claims
        +
Database constraints
        +
Transactions
        +
Concurrent integration tests

No single mechanism is treated as sufficient on its own.
33. What Protects Against Duplicate Events

Financial duplicates:

Redis
   +
PostgreSQL

Outbox duplicates:

idempotency_key
   +
database uniqueness

Downstream event duplicates:

consumer idempotency

This creates layered protection across the system.
34. Bottleneck Prevention

Primary bottleneck controls include:
M-Pesa OAuth

Use cached tokens rather than obtaining a token for every STK request.
HTTP Connections

Reuse async HTTP client connections.
STK Abuse

Use Redis-backed rate limiting.
Webhooks

Keep callback processing focused and transactionally controlled.
Notifications

Move SMS/WhatsApp work to background processing.
Event Publishing

Use the transactional outbox rather than blocking payment transactions on Kafka.
Worker Concurrency

Use atomic outbox claiming with row locks and SKIP LOCKED.
Database

Use indexes, bounded queries, short transactions, and appropriate connection
pooling.
35. Observability Requirements

The system should eventually provide correlation across:

HTTP request
   ↓
payment initiation
   ↓
MerchantRequestID
   ↓
CheckoutRequestID
   ↓
M-Pesa receipt
   ↓
payment transaction
   ↓
ledger entry
   ↓
outbox event
   ↓
Kafka event

Recommended diagnostic fields:

    Request ID

    Merchant Request ID

    Checkout Request ID

    M-Pesa receipt

    Payment transaction ID

    Outbox event ID

    User ID

    Landlord ID

    Processing duration

    Reconciliation status

Secrets must never be logged.
36. Current Infrastructure

Development infrastructure currently uses Docker for core infrastructure.

Conceptually:

Docker
 ├── PostgreSQL
 ├── Redis
 └── Kafka

The application itself runs through the Python virtual environment/Uvicorn during
local development.

The current development setup has PostgreSQL exposed on a non-default host port
and Redis/Kafka exposed for local integration testing.

Production networking and cloud infrastructure are future deployment concerns.
37. Repository Structure

The current backend architecture follows this general structure:

app/
│
├── api/
│   └── v1/
│       └── endpoints/
│
├── core/
│   ├── config.py
│   ├── dependencies.py
│   └── rate_limiter.py
│
├── integrations/
│   ├── mpesa/
│   │   └── client.py
│   └── events/
│
├── repositories/
│
├── schemas/
│
├── services/
│
├── workers/
│   └── outbox.py
│
└── Tests/
    ├── integration/
    └── unit/

Supporting database migration scripts are maintained separately.
38. Architectural Boundaries

The following boundaries should remain clear.
API Layer

Knows:

    HTTP

    Request/response schemas

    Authentication dependencies

    HTTP errors

Does not own:

    Financial business logic

    SQL workflows

    Redis algorithms

Service Layer

Knows:

    Business workflows

    Transactions

    Domain coordination

Does not own:

    HTTP formatting

    Raw external protocol mechanics where those belong to integrations

Repository Layer

Knows:

    SQL

    Database persistence

    Constraints

Does not own:

    HTTP behavior

    UI behavior

Integration Layer

Knows:

    Daraja protocol

    Kafka protocol

    Notification provider protocols

Does not own:

    Overall financial workflow orchestration

39. Security Architecture

Security is layered:

Client
  ↓
HTTPS
  ↓
Authentication
  ↓
RBAC
  ↓
Application authorization
  ↓
RLS
  ↓
Database permissions

Additional controls:

Input validation
Rate limiting
Idempotency
Audit logging
Secret isolation
Data minimization

M-Pesa credentials remain server-side and must never enter frontend bundles.
40. Architecture Decision Summary
Decision	Reason
FastAPI	Async Python API suitable for integration-heavy backend
PostgreSQL	Strong transactions, constraints, RLS and financial consistency
Redis	Fast idempotency/coordination and rate limiting
SQLAlchemy async	Async DB access with PostgreSQL
M-Pesa Daraja	Core Kenyan payment integration
Transactional outbox	Durable event publication
Kafka	Asynchronous event distribution
Separate app/system DB sessions	Separate ordinary tenant-facing access from system operations
In-process OAuth cache	Removes repeated OAuth overhead during normal process lifetime
API/service/repository layers	Separation of concerns
Next.js/React PWA	Responsive landlord and caretaker experiences
Typed API contracts	Allows frontend/backend parallel development
41. Current Architecture Status
Completed Foundation

    PostgreSQL application foundation

    PostgreSQL RLS foundation

    Separate application/system database sessions

    M-Pesa STK Push

    Daraja OAuth caching

    Shared M-Pesa HTTP client

    M-Pesa webhook ingestion

    Raw webhook persistence

    Redis idempotency

    PostgreSQL authoritative payment claim

    Reconciliation

    Exact payment allocation

    Partial payment allocation

    Overpayment credits

    Ledger processing

    Transaction rollback handling

    Transactional outbox

    Kafka publisher/worker path

    Outbox retries/backoff

    STK Push rate limiting

    Rate-limiter integration tests

    Concurrent payment integration scenarios

Current Next Phase

Authentication
      ↓
JWT/session handling
      ↓
RBAC
      ↓
Authenticated tenant/landlord context
      ↓
RLS integration
      ↓
Core API contracts
      ↓
Frontend integration

42. Reliability Hardening Still Required

Before production, explicitly validate:

Duplicate callbacks
Concurrent callbacks
Concurrent payment allocation
Rollback during reconciliation
Redis unavailable
Database unavailable
Stale Redis locks
Outbox worker crashes
Outbox concurrent claims
Deadlock scenarios
Consumer duplicate events
Long-running transactions

The goal is not to assume these failures cannot happen.

The goal is to prove the system remains correct when they do.
43. Architectural Evolution Path

The architecture is intentionally evolutionary.
Current

FastAPI
 + PostgreSQL
 + Redis
 + Kafka
 + M-Pesa

Next

Authentication
 + RBAC
 + RLS context
 + Core APIs

Then

Frontend
 + Dashboard
 + Caretaker PWA
 + Payment UX

Then

Notifications
 + SMS
 + WhatsApp
 + Automation

Then

Recovery
 + Reporting
 + Observability
 + Production scaling

Do not introduce additional distributed components merely because they are
available. Add them when an actual requirement justifies the complexity.
44. Final Architectural Invariant

The most important KodiLedger invariant is:

                    EXTERNAL PAYMENT
                           │
                           ▼
                     WEBHOOK DATA
                           │
                           ▼
                    IDEMPOTENT CLAIM
                           │
                           ▼
                     RECONCILIATION
                           │
                           ▼
                   FINANCIAL ALLOCATION
                           │
                           ▼
                         LEDGER
                           │
                           ├──────────────┐
                           ▼              ▼
                       OUTBOX          AUDIT
                           │
                           ▼
                         KAFKA
                           │
                           ▼
                ASYNCHRONOUS SIDE EFFECTS