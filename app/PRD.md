KodiLedger — Product Requirements Document (PRD)

Document: PRD.md
Product: KodiLedger
Product Type: Rental Property Management and Payment Reconciliation Platform
Primary Market: Kenya
Status: Active Development
Current Backend Branch: security-foundation-outbox

1. Product Overview

KodiLedger is a multi-tenant rental property management platform designed to reduce the manual work involved in managing residential rental properties while improving payment accuracy, financial visibility, and operational accountability.

The platform connects:

Landlords / property owners

Caretakers / property agents

Tenants

Safaricom M-Pesa

Notification services

Background processing and event infrastructure

The core product principle is:

A payment should move from initiation, through asynchronous M-Pesa confirmation, into an authoritative financial ledger without being duplicated, lost, or incorrectly allocated.

KodiLedger is designed around a FastAPI backend, PostgreSQL, Redis, Kafka/outbox processing, and a Next.js/React Progressive Web App frontend.

2. Problem Statement

Rental property management is often fragmented across notebooks, spreadsheets, M-Pesa messages, bank statements, and manual communication.

This creates several recurring problems:

Landlords lack a reliable real-time view of rent collected and arrears.

M-Pesa payments can arrive with incorrect or inconsistent account references.

Duplicate or retried payment callbacks can result in double processing if idempotency is weak.

A payment can be successfully received but remain unmatched to the intended unit.

Caretakers require operational access without exposing sensitive landlord-level financial information.

Manual cash and bank payments are difficult to audit.

Water and other variable charges require recurring field input.

Sending notifications directly inside HTTP requests can slow critical user-facing operations.

Network failures can create gaps between external payment systems and the internal ledger.

Property owners need auditable records when financial discrepancies occur.

KodiLedger addresses these problems by combining automated payment ingestion, reconciliation, tenant/property management, role-based access, immutable financial records, background processing, and operational dashboards.

3. Vision

Build a trustworthy rental operations platform where a landlord can manage properties, tenants, invoices, payments, and collections from one place while the system automatically handles payment ingestion, reconciliation, auditability, and asynchronous processing.

The product should make the financial state of every unit understandable at a glance.

4. Product Goals

4.1 Primary Goals

Automate M-Pesa payment ingestion and reconciliation.

Prevent duplicate payment processing.

Provide an authoritative financial ledger.

Provide landlord-level portfolio visibility.

Provide restricted caretaker operational workflows.

Track tenants, units, invoices, payments, and balances.

Support partial payments and overpayments.

Surface unassigned payments for manual resolution.

Preserve an audit trail for important actions.

Decouple external notifications and event publishing from critical HTTP requests.

Provide a responsive web/PWA experience suitable for desktop, tablet, and mobile use.

Provide stable API contracts that allow backend and frontend work to proceed in parallel.

4.2 Secondary Goals

Support multiple properties per landlord.

Support 1–50 rental units for the core MVP use case.

Support offline-first caretaker workflows.

Provide financial reporting and export capabilities.

Support automated SMS/WhatsApp communication through asynchronous services.

Prepare the architecture for future scale without prematurely introducing unnecessary complexity.

5. Non-Goals / Out of Scope for MVP

The following are outside the core MVP boundary:

Formal legal lease drafting

Legal dispute management

Tenant credit scoring

Formal tenant background screening

Property tax auto-filing

Legal title-deed transfers

Maintenance ticket dispatch and contractor/vendor payment processing

These may be evaluated as future products or integrations but should not drive the MVP architecture.

6. Target Users

6.1 Landlord / Property Owner

Primary administrative user.

Typical needs:

Understand portfolio performance quickly.

Know who has paid and who has not.

See arrears immediately.

Manage multiple properties and units.

Manage tenants.

Resolve unassigned payments.

Review transaction history.

Export financial information.

Manage caretaker access.

Maintain confidence that payment records are accurate.

6.2 Caretaker / Property Agent

Operational user with restricted access.

Typical needs:

View assigned units.

Check payment/occupancy status relevant to assigned units.

Enter water meter readings.

Log cash or offline payments.

Work from a smartphone in low-connectivity areas.

Receive clear confirmation when actions are synchronized.

Caretakers must not have access to landlord-level financial information.

6.3 Tenant

Primarily a passive/communication-oriented end user in the MVP.

Typical interaction:

Receives rent reminders.

Receives payment/receipt communication.

Uses normal M-Pesa flows.

May interact through secure payment links or lightweight web pages.

Does not need to install a large dedicated mobile application for the core payment workflow.

7. Core Product Workflows

7.1 Property Registration

Landlord:

Creates property.

Enters property metadata.

Creates units.

Sets rent and supported recurring charges.

Assigns tenants as needed.

7.2 Tenant Onboarding

Landlord or authorized caretaker:

Creates tenant record.

Adds full name and phone number.

Assigns a unit.

Records lease start date.

Records security deposit where applicable.

Records opening balance where supported.

7.3 M-Pesa STK Push

User:

Enters/selects payment amount and phone number.

Frontend calls backend STK Push endpoint.

Backend validates the request.

Backend obtains/reuses Daraja OAuth token.

Backend submits STK Push request.

Backend returns Daraja acceptance response.

Customer completes payment on their phone.

Safaricom asynchronously sends callback data.

Backend persists and reconciles the callback.

Final financial state is reflected in the ledger.

Important UX rule:

An accepted STK Push request is not the same as a completed payment.

The frontend must distinguish:

STK request accepted

Payment pending

Payment completed

Payment failed

Payment reversed

7.4 M-Pesa Webhook Processing

The backend webhook flow is intended to:

Extract callback metadata.

Persist raw webhook data.

Validate successful payment data.

Resolve the landlord.

Apply Redis idempotency protection.

Perform the authoritative PostgreSQL payment claim.

Reconcile the payment.

Allocate the payment to invoices/ledger.

Create an outbox event.

Mark the payment processing state.

Commit the database transaction atomically.

Roll back database work and release the Redis lock on failure.

PostgreSQL is the authoritative source of truth for payment processing; Redis is the fast-path concurrency/idempotency layer.

7.5 Invoice Allocation

Exact Payment

Payment amount exactly covers the remaining invoice balance.

Expected result:

Invoice fully allocated.

Invoice marked paid.

Ledger updated.

Outbox event created.

Partial Payment

Payment is less than the remaining invoice balance.

Expected result:

Payment allocated to invoice.

Invoice remains outstanding.

Remaining balance is preserved.

Overpayment

Payment exceeds the remaining invoice balance.

Expected result:

Remaining invoice balance is paid.

Excess is recorded as a payment credit.

Financial records preserve the overpayment.

7.6 Unassigned Payment

When a payment cannot be confidently matched:

Payment remains recorded.

Payment is marked unassigned.

Landlord sees it in the unassigned payment queue.

Landlord searches/selects the intended unit.

Assignment is confirmed.

Backend updates the authoritative records.

UI refreshes from backend state.

7.7 Manual Payment Logging

Authorized users may record non-M-Pesa payments where supported:

Cash

Bank transfer

Cheque

Other supported methods

All manual financial actions must be auditable and subject to backend authorization.

7.8 Caretaker Meter Workflow

Caretaker:

Opens assigned unit.

Views previous meter reading.

Enters current reading.

Reviews calculated consumption where supported.

Optionally attaches a meter image.

Submits the reading.

If offline, the action is queued locally.

When connectivity returns, the queue synchronizes.

User receives explicit sync status.

The interface must never imply server persistence when the action is only locally queued.

7.9 Cash / Offline Payment Workflow

Caretaker:

Selects unit.

Enters amount.

Selects payment method.

Enters reference if applicable.

Adds notes.

Confirms submission.

Backend records the payment.

Frontend displays server-confirmed status.

Duplicate clicks/submissions must be prevented.

8. MVP Feature Scope

Landlord

Authentication

Dashboard

Property management

Unit management

Tenant management

Invoice viewing/management

Payment history

M-Pesa STK Push initiation

Unassigned payment queue

Financial summaries

Reports/exports where supported

Caretaker management

Activity/audit visibility where supported

Settings

Caretaker

Authentication

Assigned-property/unit view

Occupancy/payment status

Meter reading entry

Optional meter photo capture

Cash/offline payment logging

Offline queue and synchronization

Restricted permissions

Tenant-facing

Secure payment/invoice links where supported

Payment initiation flows where supported

Receipt/status display where supported

SMS/WhatsApp communication integration through backend services

9. Dashboard Requirements

The landlord dashboard should surface the most important information first.

Required metrics

Total rent expected

Total rent collected

Total outstanding arrears

Occupancy rate

Occupied unit count

Vacant unit count

Payment/activity summary

Unit Status Grid

Conceptual states:

PAID

PENDING

OVERDUE

PARTIAL

VACANT

Status must not depend on color alone. Use text and/or icons as secondary indicators.

Recent Activity

Display relevant recent transactions/events, subject to authorization.

Unassigned Payments

Display a prominent but non-blocking alert when payments require manual assignment.

10. Security and Authorization Requirements

10.1 Authentication

The backend/frontend contract must support:

Login

Session/access-token handling

Logout

Protected routes

Expired-session handling

10.2 Roles

Core roles:

LANDLORD

CARETAKER

TENANT / secure-link-based tenant flows as applicable

10.3 Authorization

Authorization must be enforced by the backend.

The frontend should also:

Hide actions the user cannot perform.

Prevent navigation to inappropriate screens.

Display appropriate 401/403 states.

Frontend hiding is a UX layer, not the security boundary.

10.4 Tenant Isolation

PostgreSQL Row-Level Security is part of the system architecture and should remain a defense-in-depth layer.

The authenticated user's tenant/landlord context must be correctly propagated into backend authorization and RLS handling.

10.5 Sensitive Data

Do not expose or log:

Passwords

JWTs or long-lived credentials

M-Pesa consumer secrets

M-Pesa passkeys

Private service credentials

Tenant personal data must be shown only to authorized users and only when needed.

11. Financial Integrity Requirements

Financial records are authoritative in the backend.

The frontend must not be the source of truth for:

Payment status

Invoice balances

Ledger balances

Allocation

Overpayment credits

Reconciliation

Revenue totals

Frontend calculations may be used for previews or user feedback, but final values must come from the backend.

12. Reliability Requirements

KodiLedger must be designed to tolerate external retries and partial failures.

12.1 Database Transactions

Payment reconciliation should operate within a transaction boundary.

On failure:

PostgreSQL transaction is rolled back.

Redis idempotency lock is released when appropriate.

No partial financial state should remain committed.

12.2 Idempotency

Use two layers:

Redis fast-path locking.

PostgreSQL authoritative payment claiming/constraints.

A duplicate webhook must not double-credit a payment.

12.3 Race Conditions

Concurrency protection must cover:

Duplicate callbacks.

Concurrent callbacks for the same receipt.

Concurrent payment allocation.

Concurrent outbox worker claims.

12.4 Deadlocks

The system should use consistent database lock ordering and should contain explicit deadlock/concurrency tests.

Do not describe the system as mathematically deadlock-proof until dedicated deadlock testing and lock-order analysis are complete.

12.5 Outbox Pattern

Financial state changes and event creation should remain transactionally coupled.

Outbox processing must support:

Pending state

Worker claiming

Publishing

Retry/backoff

Failure tracking

Idempotent event insertion

The architecture uses Kafka for payment.processed event publishing.

12.6 At-Least-Once Delivery

The outbox path should be treated as at-least-once.

Future consumers must therefore be idempotent.

13. Performance Requirements

M-Pesa Initiation

The application has already been measured in sandbox testing.

Observed behavior:

First STK request in a fresh process includes OAuth acquisition.

Subsequent requests can reuse the cached token.

The Daraja STK request itself has been observed substantially faster than the full first-request path.

Current M-Pesa integration requirements:

Reuse HTTP client connections.

Cache Daraja OAuth tokens.

Avoid unnecessary OAuth requests.

Do not place expensive notification processing inside the critical STK/webhook path.

Rate Limiting

The STK Push endpoint includes Redis-backed rate limiting.

The current development configuration limits STK Push initiation requests per IP within a configurable time window.

Do not apply this same rate-limiting behavior blindly to the M-Pesa callback endpoint.

General Backend Performance

Avoid:

Blocking external services inside database transactions when possible.

Synchronous notification dispatch during user requests.

Repeated database fetches for the same screen.

Unbounded list queries.

Duplicate downstream processing.

14. Backend Architecture Baseline

Application

FastAPI

Python 3.11/3.12

Uvicorn

Pydantic v2

Database

PostgreSQL 15

Async SQLAlchemy

asyncpg

Row-Level Security

Caching / Distributed Coordination

Redis

Redis-based idempotency

Redis rate limiting

Eventing

Transactional outbox

Kafka

Idempotent publisher

Background outbox worker

Retry with exponential backoff

Payments

Safaricom Daraja API

M-Pesa STK Push

M-Pesa callback/webhook

OAuth token caching

Frontend

Next.js

React

TypeScript

Responsive web application

Progressive Web App foundations

15. Frontend Product Requirements

Frontend Information Architecture

Suggested high-level routes:

/
├── /login
├── /dashboard
├── /dashboard/properties
├── /dashboard/properties/[propertyId]
├── /dashboard/tenants
├── /dashboard/tenants/[tenantId]
├── /dashboard/invoices
├── /dashboard/payments
├── /dashboard/payments/unassigned
├── /dashboard/reports
├── /dashboard/caretakers
├── /dashboard/settings
│
├── /caretaker
├── /caretaker/units
├── /caretaker/meters
└── /caretaker/payments

These routes are design targets and should be reconciled with the final FastAPI/OpenAPI contract.

Frontend Principles

Responsive by default.

Mobile-first for caretaker workflows.

Large readable financial figures.

Clear status hierarchy.

Accessible forms.

Explicit loading/error/empty states.

Strong form validation.

No frontend-owned financial truth.

No secrets in browser code.

16. API Contract Strategy

Backend and frontend development will proceed in parallel.

The frontend should use a typed abstraction:

FastAPI OpenAPI
      ↓
Generated / maintained TypeScript types
      ↓
Typed API service layer
      ↓
React / Next.js UI

The frontend must not invent production endpoints.

While backend endpoints are still being implemented, the frontend may use mock adapters that implement the same interfaces as the eventual API services.

Example:

DashboardService
 ├── MockDashboardService
 └── ApiDashboardService

Once the backend contract stabilizes:

Update the types.

Implement real API adapters.

Replace mock data.

Keep component interfaces stable.

Add integration tests.

17. API Domains

The core frontend-facing API domains are expected to include:

Authentication

Login

Logout

Session/profile

Token/session handling

Dashboard

Portfolio summary

Occupancy

Collection metrics

Recent transactions

Properties

List

Create

Update

Detail

Units

List

Create

Update

Detail

Occupancy/payment status

Tenants

List

Create

Update

Detail

Invoices

List

Detail

Current balance

Payment state

Payments

STK Push

Payment history

Payment detail

Payment state

Unassigned payment queue

Assignment

Caretakers

List

Create/invite

Status

Revoke access

Reports

Financial summaries

PDF/CSV/Excel export where available

18. Notifications

Notifications should be asynchronous wherever possible.

Future/target integrations:

SMS

WhatsApp Business

Email where required

Critical HTTP requests should not wait on notification delivery.

The notification architecture should support retries and telecom/network failures.

19. Auditability

Important state changes should be auditable.

Examples:

User login

Tenant changes

Property changes

Unit changes

Manual payments

Payment assignment

Meter submissions

Caretaker access changes

Financial adjustments

Audit records should capture the relevant actor, timestamp, action, resource, and outcome when supported by the backend.

20. Reporting Requirements

The product should eventually provide:

Monthly Financial Statement

Gross revenue

Rent collections

Utility collections

Arrears

Payment methods

Relevant financial adjustments

Data Export

Transaction logs

Accounting/audit data

Bank/Safaricom-compatible records where appropriate

Exports should be generated from authoritative backend data.

21. Offline-First Requirements

Offline capability is primarily for the caretaker application.

The application should expose:

ONLINE
OFFLINE
SYNCING
SYNCED
SYNC FAILED

Supported offline actions should be intentionally defined rather than making the entire system offline-capable by default.

Sensitive financial data should not be cached unnecessarily.

Queued actions must be:

Persistent enough to survive page refresh/restart where appropriate.

Retryable.

Clearly visible to the caretaker.

Reconciled against server responses.

22. Accessibility

The UI must support:

Keyboard navigation

Semantic HTML

Screen-reader labels

Visible focus states

Accessible dialogs

Accessible forms

Adequate contrast

Non-color-only status communication

Clear validation messaging

23. Error Handling

Standard API behavior

Handle:

400 Validation error

401 Unauthenticated

403 Unauthorized

404 Not found

409 Conflict

422 Validation/schema issue

429 Rate limited

500 Internal server error

502/503 Upstream/dependency failure

The frontend should display human-readable messages rather than raw stack traces or database errors.

Example:

Instead of:

IntegrityError: duplicate key

display:

This payment has already been processed.

24. Testing Requirements

Backend

Required categories:

Unit tests

Integration tests

M-Pesa webhook tests

Idempotency tests

Concurrency tests

Invoice allocation tests

Outbox tests

Rate-limit tests

Rollback/failure tests

Frontend

Recommended:

Vitest

React Testing Library

Playwright

Priority frontend tests:

Authentication

Protected routes

Role routing

Dashboard

Property management

Tenant management

Invoice states

Payment states

Unassigned payment assignment

Caretaker workflows

Offline queue

Authorization UX

Reliability Test Matrix

Explicitly test:

Duplicate webhook
Concurrent duplicate webhook
Concurrent payments
Partial payment
Overpayment
Missing/invalid payment metadata
Database failure during reconciliation
Redis unavailable
Stale Redis lock
Outbox worker concurrency
Deadlock scenarios
Rollback after intermediate financial operation

25. Current Implementation Status

Completed

PostgreSQL-backed application foundation

PostgreSQL RLS foundation

Separate application/system database access pattern

M-Pesa STK Push initiation

Daraja OAuth token caching

Reusable HTTP client for M-Pesa calls

M-Pesa webhook ingestion

Raw webhook persistence

Redis fast-path idempotency

PostgreSQL authoritative idempotency

Payment reconciliation service

Invoice allocation

Partial payments

Overpayment credits

Ledger updates

Transaction rollback handling

Transactional outbox

Kafka publisher/worker path

Outbox retry/backoff architecture

STK Push Redis rate limiting

Rate-limiting integration tests

Concurrent payment integration scenarios

GitHub versioning of the current M-Pesa/rate-limiter work

Current Git milestone

35f1005  feat: add STK push rate limiting
a364db3  fix: restore STK push and optimize M-Pesa client

In Progress / Next

Authentication

JWT/session architecture

Role-based authorization

Tenant-aware authorization context

RLS integration with authenticated user context

Landlord API contracts

Caretaker API contracts

Tenant/API payment contracts

Stable OpenAPI contract

Reliability hardening and failure injection

26. Development Roadmap

Phase 1 — Database and Ledger Foundation

Status: Completed foundation.

Deliverables:

Core schema

PostgreSQL

RLS

Financial transaction foundation

Ledger architecture

Phase 2 — M-Pesa and Payment Processing

Status: Substantially completed.

Deliverables:

STK Push

OAuth

Callback ingestion

Redis idempotency

PostgreSQL authoritative claims

Reconciliation

Allocation

Outbox

Kafka

Rate limiting

Phase 3 — Authentication, RBAC and API Contracts

Status: Next.

Deliverables:

Authentication

Roles

Authorization

RLS/user context integration

Core API domains

OpenAPI contracts

Phase 4 — Landlord and Caretaker APIs

Deliverables:

Dashboard

Properties

Units

Tenants

Invoices

Payments

Unassigned payments

Caretaker workflows

Phase 5 — Frontend Application

Frontend work can proceed in parallel while backend Phase 3/4 is being built.

Initial frontend milestone:

App shell

Login

Role-based routing

Dashboard

Property screens

Mock API adapters

Integration milestone:

Replace mocks with real backend adapters

Integrate authentication

Connect financial data

Connect payment state

Phase 6 — Notifications and Automation

SMS

WhatsApp

Scheduled reminders

Receipt dispatch

Background jobs

Phase 7 — Recovery, Reporting and Advanced Reconciliation

Nightly reconciliation

Missed-callback recovery

Reporting

Exports

Advanced audit/recovery workflows

Phase 8 — Production Hardening

Load testing

Concurrency testing

Deadlock testing

Failure injection

Observability

Deployment

Security review

Operational runbooks

27. Definition of Done — Backend MVP

The backend MVP should not be considered complete until:

Authentication works.

Roles are enforced.

Tenant/landlord isolation is enforced.

RLS is correctly connected to authenticated context.

Property APIs work.

Unit APIs work.

Tenant APIs work.

Invoice APIs work.

Payment APIs work.

Unassigned payment workflow works.

STK Push works.

Callback processing works.

Idempotency works.

Invoice allocation works.

Ledger writes are transactionally safe.

Outbox events are reliable.

Rate limiting works.

Concurrency tests pass.

Rollback tests pass.

Deadlock scenarios have been tested.

Redis/database failure behavior is understood.

API contracts are documented in OpenAPI.

No secrets are committed.

28. Definition of Done — Frontend MVP

The frontend MVP should not be considered complete until:

Authentication works.

Role-aware routing works.

Landlord dashboard works.

Property management works.

Unit management works.

Tenant management works.

Invoice screens work.

Payment screens work.

Unassigned payment workflow works.

STK Push UX correctly distinguishes initiation from completion.

Caretaker mobile workflow works.

Offline queue works for supported operations.

Error/loading/empty states exist.

API integration is typed.

Sensitive data is appropriately protected.

Responsive layouts work.

Accessibility requirements are addressed.

E2E tests cover the main user journeys.

29. Critical Product Principles

Principle 1 — Backend is the financial authority

The browser never becomes the accounting system.

Principle 2 — M-Pesa is asynchronous

STK initiation and payment completion are separate states.

Principle 3 — Redis improves speed; PostgreSQL decides truth

Redis idempotency is a fast-path protection layer.

PostgreSQL remains authoritative.

Principle 4 — Financial operations are transactional

Payment, allocation, ledger changes, and outbox creation must be coordinated so failures do not leave inconsistent financial state.

Principle 5 — Roles are enforced server-side

Frontend role restrictions are for UX; backend authorization and RLS provide the security boundary.

Principle 6 — Notifications are asynchronous

SMS/WhatsApp work should not block critical payment or dashboard operations.

Principle 7 — Design for failure

Network failures, duplicate callbacks, retries, stale locks, worker failures, and partial integrations are normal operating conditions, not exceptional afterthoughts.

Principle 8 — Develop backend and frontend in parallel

The frontend should progress using stable interfaces and mock adapters, then integrate progressively as backend API contracts stabilize.

30. Key Risks

Risk

Impact

Mitigation

Duplicate M-Pesa callbacks

Double credit

Redis + PostgreSQL idempotency

Missing callbacks

Payment not reconciled

Recovery/reconciliation jobs

Redis failure

Reduced fast-path protection

PostgreSQL remains authoritative

Database failure mid-transaction

Partial financial state

Transaction rollback

Concurrent invoice allocation

Incorrect balance

Database concurrency controls + tests

Deadlock

Transaction failure

Consistent lock ordering + explicit tests

Outbox duplicate publishing

Duplicate downstream work

Idempotent consumers

Stale worker claims

Delayed event processing

Stale-claim recovery

Telecom/API latency

Slow payment initiation

OAuth caching + reusable HTTP client

Rate abuse

Excessive STK requests

Redis-backed rate limiting

Unauthorized caretaker access

Data leakage

RBAC + backend authorization + RLS

Offline sync conflict

Duplicate/incorrect field data

Explicit queue/status/reconciliation

API contract drift

Frontend breakage

OpenAPI + typed adapters

31. Success Metrics

Financial accuracy

Zero known duplicate financial credits caused by duplicate webhooks.

Reconciliation exceptions are visible and recoverable.

Partial and overpayments are represented correctly.

Operational efficiency

Landlord can understand collection status without inspecting raw transactions.

Unassigned payments can be resolved through a dedicated workflow.

Caretakers can record field operations without exposing landlord financials.

Reliability

Duplicate callbacks are safely handled.

Transaction failures leave no partial financial state.

Outbox failures are retried.

Concurrent processing has deterministic outcomes.

User experience

Dashboard loads quickly enough for normal web/mobile use.

Critical workflows have clear loading and confirmation states.

Caretaker workflows remain usable under intermittent connectivity.

32. Future Opportunities

Potential future extensions include:

Advanced property analytics

Scheduled rent reminders

Automated SMS receipts

WhatsApp conversational workflows

Nightly statement reconciliation

Financial statement generation

Advanced audit/event timelines

Real-time dashboard updates

Advanced reporting

Multi-channel notifications

Expanded offline workflows

Cloud deployment and autoscaling

Observability/tracing infrastructure

These should be implemented only after the core MVP workflows are stable.

33. Product Boundary

KodiLedger is fundamentally:

A rental operations and financial reconciliation platform that connects property management workflows with reliable payment processing.

Its value comes from combining:

PROPERTY MANAGEMENT
        +
TENANT MANAGEMENT
        +
INVOICING
        +
M-PESA
        +
RECONCILIATION
        +
LEDGER
        +
AUDITABILITY
        +
ROLE-BASED OPERATIONS
        +
ASYNC EVENT PROCESSING

The product should remain focused on these core workflows rather than becoming a generic ERP.

34. Immediate Next Milestone

Backend

Authentication → RBAC → tenant-aware authorization → RLS context → core API contracts.

Frontend in parallel

App shell → Login → Role routing → Dashboard → Property/Unit screens using mock adapters.

Integration point

When authentication, RBAC, RLS-aware API behavior, and the core landlord/property/unit/tenant/invoice/payment API contracts are stable, replace frontend mocks with real services and begin full backend/frontend integration testing.