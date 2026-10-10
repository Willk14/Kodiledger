# KodiLedger Domain Model

**Status:** Implementation-based reference. Statements labeled **Current behavior** describe code and database rules that exist today. Accepted domain rules are listed separately from unimplemented proposals.

This document describes the implemented property, invoice, and payment concepts that shape the API. It is a domain guide, not a replacement for the SQL migrations, API contract, or accepted technical decisions.

## Core concepts

| Concept | Meaning in KodiLedger | Main relationships and current rules |
|---|---|---|
| **Landlord** | The owner scope for properties and financial records. | A landlord owns properties, units, tenants, invoices, payment transactions, and ledger entries. Authenticated API scope is derived from the active local membership and enforced through PostgreSQL RLS on protected routes. |
| **Property** | A rental property managed in a landlord's scope. | A property contains units. The property stores a unit count maintained by the unit workflow. |
| **Unit** | A rentable space in a property. | A unit belongs to a property and landlord. Tenants, invoices, and ledger entries refer to a unit. |
| **Tenant** | A person associated with a unit and landlord. | Active tenants can be matched to successful payments by payer phone during reconciliation. A landlord can select an active tenant in their own scope when resolving an unassigned payment. |
| **Invoice** | A tenant's rental obligation for a billing period. | An invoice refers to a landlord, unit, and tenant. `total_amount` is generated from rent, water, garbage, and security charges. Allocations record payment applied to an invoice; `is_paid` is updated by the allocation workflow when the allocated total settles the invoice. |
| **Payment transaction** | A normalized record of a payment receipt or payment attempt. | A successful M-Pesa callback creates a transaction with a unique receipt number, persisted amount, method, status, and optional tenant. An unmatched receipt has no tenant until resolved. Payment amount is the receipt amount, not necessarily the amount applied to an invoice. |
| **Raw payment webhook** | The retained provider callback payload and correlation data. | It is an input/audit record for reconciliation. Its internal ID is not part of the public unassigned-payment list response. |
| **Payment processing record** | Receipt-level reconciliation and retry state. | The callback workflow claims a receipt once. An unmatched payment is marked `UNASSIGNED`; resolution marks it assigned/completed in the same financial transaction. |
| **Unassigned payment** | A successful callback that reconciliation could not match to an active tenant by payer phone. | It remains landlord-scoped and unresolved until a landlord selects an active same-landlord tenant. Repeating resolution after success returns a conflict and does not repeat financial writes. |
| **Payment allocation** | The amount of one payment applied to one invoice. | The database enforces one row per payment/invoice pair and a positive amount. The allocator writes at most the payment's available amount and the invoice's remaining balance. |
| **Payment credit** | Unapplied payment funds recorded for later tenant use. | The allocator creates an `AVAILABLE` credit for invoice overpayment or the remaining payment amount when no unpaid invoice exists. Immutable application rows record amounts subsequently applied to invoices. The credit read API reports original and available amounts. |
| **Ledger entry** | A durable financial history record. | Current payment workflows record one full-payment `CREDIT` linked to the payment transaction; it is not a measure of how much was applied to rent. Invoice settlement is represented by allocations and credit applications. The read-only Ledger API returns this persisted history. |
| **Outbox event** | A durable instruction to publish a committed domain event asynchronously. | The `PAYMENT_PROCESSED` row commits with the financial records. A worker publishes it after commit; delivery may repeat, so consumers need deduplication. |

The database has foreign keys for these relationships, but some cross-record business rules—such as matching an invoice's tenant and unit—are validated by application workflows rather than a composite database constraint. See [DATABASE.md](DATABASE.md) for the persisted schema and constraints.

## Payment and invoice flow

```text
STK Push initiation
        │ initiation is not payment confirmation
        ▼
M-Pesa callback → raw webhook and receipt claim
        ▼
Completed payment transaction
        ├── active tenant matched by phone
        │      └── existing allocator → invoice allocation / possible credit
        └── no active tenant matched
               └── unassigned payment → landlord selects active tenant
                                      → same existing allocator
        ▼
Full receipt ledger entry + transactional outbox event
        ▼
PostgreSQL commit → asynchronous outbox publication
```

The matched callback path and landlord resolution path reuse `InvoiceAllocationService`; there is one allocation algorithm. Reconciliation and resolution keep their database writes in the caller's PostgreSQL transaction. The API route owns commit and rollback for resolution. Redis is not authoritative for payment, allocation, credit, or invoice balances.

## Financial invariants

- **Payment is a receipt.** The persisted payment transaction amount is the amount received. A successful payment ledger credit records that full amount.
- **Allocation is invoice application.** An allocation does not exceed either the available payment funds or the invoice's remaining balance.
- **Payment conservation:** the allocator calculates available funds as the persisted payment amount minus the sum of its allocations and extant payment credits. Current code counts all extant credit statuses as consumed; no credit-release operation exists.
- **Invoice conservation:** remaining invoice balance is its generated total less payment allocations and credit applications. Tenant-level PostgreSQL locking serializes payment allocation, credit application, and invoice creation; payment and credit rows are locked before invoices when those rows are involved.
- **Overpayment:** when a payment exceeds the selected invoice's remaining balance, the allocator records the excess as a payment credit. It does not create an extra ledger receipt for the excess.
- **Atomicity:** payment assignment, allocation, credit, invoice state, ledger, processing/resolution state, and outbox insertion must commit together or roll back together.
- **Idempotency:** a receipt is claimed uniquely; the unassigned-payment row is locked during resolution; an already-resolved command returns HTTP 409 without new financial effects.
- **PostgreSQL authority:** database constraints and row locks protect financial correctness. Redis is a coordination or fast-path mechanism only.

## Current unassigned-payment resolution behavior

The request selects only a `tenant_id`. The API derives landlord scope from the authenticated principal, requires `LANDLORD` plus `PAYMENT_ASSIGN`, verifies that the payment and active tenant belong to that landlord, and uses the normal RLS-bound database session. The server derives payment status and amount, tenant unit, invoice, allocation, ledger, and outbox data from PostgreSQL.

The lock order is **unassigned payment → payment transaction → invoice**. Other allocation callers use **payment transaction → invoice**. The resolver holds one PostgreSQL transaction across assignment, allocation/credit, invoice update, ledger, processing state, outbox, and resolved metadata.

**Current behavior when there is no unpaid invoice:** resolution still succeeds. The allocator returns `UNALLOCATED` with `NO_UNPAID_INVOICE` and records the remaining available amount as an `AVAILABLE` payment credit for the selected tenant. It creates no invoice allocation and changes no invoice state. The full receipt is recorded in the ledger, the outbox event is written, and the payment is marked resolved for the selected tenant.

**Current behavior for partial allocation:** when an invoice has a remaining balance, the payment is allocated up to that balance. If funds exceed the balance, the excess is recorded as an available payment credit. If the payment is smaller than the balance, `is_paid` remains false and the allocation records the partial settlement.

## Accepted domain rule: payment received with no unpaid invoice

**Accepted:** when a completed payment is linked to a tenant and that tenant has no unpaid invoice, record the remaining available amount as an `AVAILABLE` payment credit linked to that tenant and source payment. Do not create an invoice allocation or mark any invoice paid. Keep the full receipt ledger entry and credit creation in the same PostgreSQL transaction. See [Decision 6](decisions.md#decision-6-preserve-payments-with-no-unpaid-invoice-as-tenant-credit).

This treats the amount as funds owed to or held for the tenant, preserves payment conservation, and gives a future invoice-application workflow a durable balance to reference. The rule applies through the existing allocation workflow for matched callbacks and unassigned-payment resolution; it does not add a second allocation engine.

`PaymentCredit` stores the immutable source payment amount. `payment_credit_applications` records applied amounts and invoice targets; the read API exposes original and remaining available amounts. The API exposes no credit mutation endpoint; normal payment allocation and invoice creation apply credits internally.

### Accepted domain rule: automatic application of available credit

When a payment is allocated or resolved, after its payment amount is applied to the oldest unpaid invoice, any overpayment credit is automatically applied FIFO to the oldest unpaid invoice balances. When an invoice is created, existing available credits for that tenant are automatically applied FIFO to unpaid invoices, including the new invoice if older balances have already been settled. Each application is capped at both remaining credit and invoice balance; any remainder stays available. The caller cannot select another invoice or tenant. These writes share the enclosing PostgreSQL transaction. See [Decision 7](decisions.md#decision-7-automatically-apply-available-credits-to-unpaid-invoices).

Each application is an immutable row linking a payment credit to an invoice with a positive amount, timestamp, and unique idempotency key. The original credit amount remains unchanged. Available amount is original amount less committed applications. A credit may be applied across invoices, and an invoice may receive applications from credits. Refund and cancellation workflows remain unspecified and unavailable.

## Current API boundary

- `GET /api/v1/unassigned-payments` lists unresolved receipts in the authenticated landlord scope.
- `POST /api/v1/unassigned-payments/{payment_id}/resolve` assigns an active same-landlord tenant and runs the existing financial workflow.
- Payment-scoped allocation and credit routes are reads. There is no generic allocation CRUD, arbitrary invoice selector, credit-application command, refund command, or unassigned-payment detail route.
- Caretakers are not authorized to resolve payments in the current API; resolution requires the landlord role.

See [API.md](API.md) for request/response schemas and status codes, [SECURITY.md](SECURITY.md) for authorization and RLS controls, and [decisions.md](decisions.md) for accepted technical choices and their guardrails.
