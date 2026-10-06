# Technical Decisions

This file records decisions that are implemented or accepted for KodiLedger. **Benefits and costs** summarize each choice's trade-offs. **Guardrails** state constraints future changes must preserve. Revisit a decision when its stated trigger occurs; do not silently replace an accepted decision without recording the new choice and marking the old one superseded.

## Decision 8: Stabilize the Current API Contract Before Supabase Database Integration

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

KodiLedger is preparing to integrate with Supabase. Changing database hosting while endpoint behavior and the documented API surface are still drifting would make integration failures harder to localize and could accidentally turn provider-specific behavior into an API change.

### Trade-offs considered

1. Integrate Supabase immediately and adjust endpoint behavior as issues arise: starts database work sooner, but combines API and infrastructure changes and complicates verification.
2. Stabilize the implemented API surface first, then rehearse Supabase as a database-only integration: adds a verification step before provider setup, but isolates the migration and gives it a known behavior baseline.
3. Freeze every planned future endpoint and behavior now: appears comprehensive, but requires inventing contracts for workflows that are not yet implemented or decided.

### Decision

Treat the currently implemented HTTP routes, request/response schemas, authorization behavior, and error outcomes documented in `API.md` and generated OpenAPI as the stable baseline for Supabase database integration. Keep future/unimplemented endpoints explicitly planned. Revisit the baseline through a deliberate API change when required; this decision does not make the API permanently immutable.

### Guardrails

- **One implementation source:** registered FastAPI routes, schemas, dependencies, and generated OpenAPI define implemented behavior; documentation must match them.
- **No invented surface:** do not document a planned endpoint as implemented or create one merely to make the contract look complete.
- **Test the surface:** contract tests must fail when a route or method is added or removed without an intentional contract update.
- **Separate provider integration:** initial Supabase work changes database connectivity and deployment configuration only; keep OIDC, route paths, response schemas, and financial behavior unchanged.
- **Preserve financial boundaries:** keep PostgreSQL transaction, RLS, and separate application/system database-role guarantees under real PostgreSQL tests.
- **Document approved API changes:** update OpenAPI checks, `API.md`, auth/security/domain docs as relevant, and the roadmap in the same change.

### Why

The current API contract is the integration boundary between clients and the backend. Stabilizing only what exists avoids coupling API design to Supabase while leaving genuinely future workflows open for later design.

### Trade-offs and consequences

**Benefits:**
- Supabase migration regressions can be separated from endpoint contract changes.
- Clients gain a clear reference for implemented routes and behavior.
- Future domains remain free to receive deliberate, reviewed contracts.

**Costs:**
- Contract verification is additional work before provisioning and migration rehearsal.
- The route manifest test requires an intentional edit when the API surface changes.

### Revisit when

A required client or product workflow needs an incompatible or missing API behavior, or the Supabase integration reveals a genuine constraint that cannot be handled behind the existing contract. Record that change separately and update affected contracts before rollout.

### Related links

- [API contract](API.md)
- [Authentication and authorization](auth.md)
- [Supabase integration roadmap](roadmap.md#api-contract-stabilization-before-supabase)

## Decision 1: Keep Allocation Writes in the Unassigned-Payment Resolution Workflow

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

Payment callbacks already allocate matched payments automatically. Unmatched payments are handled through a landlord resolution workflow that assigns an active tenant and then runs the existing allocation, credit, ledger, and outbox operations. A separate allocation command could duplicate that financial workflow or let clients choose financial values the server must derive.

### Trade-offs considered

1. Add generic `POST /api/v1/allocations` and allocation collection/detail routes: offers explicit payment/invoice operations, but creates a second public financial command and requires a separate ownership and financial-validation contract.
2. Expose `InvoiceAllocationService` directly from a route: reuses allocation code, but bypasses the application orchestration for assignment, ledger, outbox, processing, and resolution state.
3. Keep callback allocation internal and use `POST /api/v1/unassigned-payments/{payment_id}/resolve` for unmatched payments: follows the existing workflow and transaction boundary, but does not provide arbitrary manual payment-to-invoice allocation.

### Decision

Use the existing unassigned-payment resolution endpoint as the only public allocation write command. Keep payment allocation and credit reads under payment-scoped routes. Do not add generic allocation CRUD or expose `InvoiceAllocationService` to HTTP callers.

### Guardrails

- **Keep one command boundary:** callback reconciliation handles matched payments; the resolve endpoint handles unmatched payments. Do not create a second allocation engine.
- **Keep client authority narrow:** the request accepts only `tenant_id`. Derive landlord, payment status and amount, invoice, allocation, ledger, and outbox values on the server.
- **Preserve authorization:** require `LANDLORD` plus `PAYMENT_ASSIGN`, verify an active tenant in the same landlord scope, and use the normal RLS session.
- **Preserve retry behavior:** a previously resolved payment returns 409 without repeating financial effects.

### Why

This preserves one orchestration path for each current payment workflow. The resolver derives landlord and payment data from authenticated scope and persisted rows, accepts only `tenant_id`, and reuses the concurrency-safe allocator. It keeps assignment, allocation, ledger, outbox, and processing effects within one command.

### Trade-offs and consequences

**Benefits:**
- No second financial command can diverge from callback or resolution behavior.
- Clients cannot choose payment amounts, invoice ownership, allocation state, or ledger/outbox values.

**Costs:**
- Landlords cannot use this API to choose an arbitrary invoice for an already assigned payment.
- A resolved payment retry returns 409 rather than replaying the original success response.

### Revisit when

Product requirements call for manual allocation or reallocation of already assigned payments. Any new command must reuse the current allocator and preserve landlord/tenant ownership, payment and invoice conservation, RLS, and the atomic financial write set.

### Related links

- [API contract](API.md#16-allocation-api)
- [Unassigned-payment API](API.md#17-unassigned-payment-api)
- [Allocation architecture](ARCHITECTURE.md)

## Decision 2: Use PostgreSQL Row Locks in Payment-Then-Invoice Order

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

Concurrent allocation requests can otherwise spend the same payment balance or apply separate payments beyond an invoice balance. Allocation can touch different invoices for one payment or the same invoice for different payments, so locking only one side does not protect both balances.

### Trade-offs considered

1. Use Redis as the primary allocation lock: provides coordination, but Redis cannot be the authority for durable financial correctness.
2. Lock only the invoice: protects its remaining balance, but does not serialize use of one payment across multiple invoices.
3. Lock the payment transaction first and the selected invoice second: serializes payment consumption and invoice balance updates in PostgreSQL, at the cost of waiting when requests share either row.

### Decision

Use PostgreSQL `SELECT ... FOR UPDATE` locks, always acquiring the payment transaction lock before the invoice lock. While holding the payment lock, compute available funds from the persisted payment amount less existing allocated amounts and all extant payment-credit amounts. Existing credits count as consumed regardless of status until the domain has an explicit operation that releases their source-payment balance. After locking the invoice, compute its remaining balance and allocate no more than the lesser of those two values.

### Guardrails

- **Lock order is mandatory:** allocation uses payment, then invoice. Unassigned-payment resolution adds an unassigned-payment lock before that shared order: unassigned payment → payment transaction → invoice. No workflow may acquire an unassigned-payment lock after acquiring the payment lock. Matched webhook reconciliation uses payment → invoice; unmatched reconciliation inserts the unassigned row without creating a reverse lock path.
- **PostgreSQL owns correctness:** do not replace row locks with Redis as the sole guarantee.
- **Use persisted balances:** payment availability is persisted payment amount minus allocated amounts and all extant payment-credit amounts; invoice availability is invoice total minus its allocated amount.
- **Prove concurrency behavior:** changes to the lock protocol require real PostgreSQL tests for same-payment and same-invoice races.

### Why

The payment lock prevents concurrent requests from observing and spending the same available payment funds. The invoice lock prevents requests using different payments from over-allocating the same invoice. A consistent lock order reduces deadlock risk. PostgreSQL remains the correctness boundary if Redis is unavailable.

### Trade-offs and consequences

**Benefits:**
- Concurrent allocation requests preserve payment and invoice conservation in the database.
- The allocator does not rely on Redis for financial correctness.

**Costs:**
- Requests sharing a payment or invoice may wait on row locks.
- Every future writer that changes allocation/credit consumption must follow the same lock protocol.

### Revisit when

Allocation supports multiple invoices per request, credit application/reversal changes the consumption model, or a new writer cannot follow payment-then-invoice ordering. Review lock ordering and add PostgreSQL concurrency coverage before changing it.

### Related links

- [Allocation and financial invariants](API.md#21-financial-api-invariants)
- [Allocation architecture](ARCHITECTURE.md)
- [PostgreSQL allocation tests](../app/Tests/security/test_postgres_rls.py)

## Decision 3: Commit Financial Effects and Outbox Together in PostgreSQL

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

A successful resolution can create an allocation and payment credit, update invoice state, assign the payment, create a ledger entry, update processing and resolution state, and record a `PAYMENT_PROCESSED` event. Committing only part of these writes would leave financial records inconsistent.

### Trade-offs considered

1. Commit allocation first and write ledger/outbox separately: shortens individual transactions, but permits partially committed financial state.
2. Publish directly to Kafka during the request: provides immediate publication, but PostgreSQL rollback cannot undo a published event.
3. Keep all database effects in the caller's PostgreSQL transaction and persist the event through the transactional outbox: provides atomic database state, while event delivery remains asynchronous.

### Decision

The application service orchestrates the financial write set without committing. The route commits once after the service succeeds and rolls back on failure. Allocation/credit, invoice state, payment assignment, ledger, processing/resolution records, and outbox insertion share the same PostgreSQL transaction. Kafka publication remains the outbox worker's responsibility after commit.

### Guardrails

- **One database transaction:** the service must not commit independently. The route commits only after every required database write succeeds and rolls back on failure.
- **No partial success:** do not return success if allocation, invoice state, ledger, processing/resolution state, or outbox insertion failed.
- **Keep Kafka outside the financial transaction:** persist the outbox row in the transaction; publish after commit through the worker.
- **Retain failure coverage:** test rollback when ledger and outbox writes fail after earlier financial writes have executed.

### Why

PostgreSQL can atomically commit or roll back the financial records and durable event intent. The outbox prevents a successful HTTP response when ledger or outbox persistence failed without making Kafka availability part of the financial transaction.

### Trade-offs and consequences

**Benefits:**
- Allocation, invoice state, ledger, and outbox intent cannot partially commit through this command.
- Kafka outages leave durable publication work for retry without undoing a valid financial commit.

**Costs:**
- Event publication is asynchronous and may be delivered more than once; consumers need deduplication.
- The transaction holds payment and invoice locks until all database writes complete.

### Revisit when

The financial write set changes, ledger/outbox storage moves, or a new side effect is proposed inside the request. External publication must not be added to the database transaction without a new consistency design.

### Related links

- [Unassigned-payment API and transaction behavior](API.md#17-unassigned-payment-api)
- [Transaction boundaries](ARCHITECTURE.md)
- [Security financial boundary](SECURITY.md#8-financial-security)

## Decision 4: Derive Authorization Scope from Membership and Enforce It with RLS

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

Financial commands must not let request fields or token claims choose a landlord, role, tenant ownership, payment amount, or invoice. Application checks also need a database isolation boundary for cross-landlord records.

### Trade-offs considered

1. Trust role and landlord values supplied by the client or token: simple to integrate, but those values are forgeable and cannot authorize financial access.
2. Use application ownership filters only: keeps checks in the API, but a missed filter can expose or mutate another landlord's rows.
3. Resolve verified identity to an active local membership, enforce route role/permission, and bind that trusted scope to a normal PostgreSQL RLS session: adds membership and database setup requirements, but layers authorization and row isolation.

### Decision

Use the verified identity and active local membership as the source of user, role, landlord, and tenant context. Require `LANDLORD` plus `PAYMENT_ASSIGN` for unassigned-payment resolution, accept only the tenant selection needed by that workflow, and use `get_rls_db` for its database work. PostgreSQL RLS remains an isolation backstop; client-supplied scope and role are not authority.

### Guardrails

- **Trust membership, not claims or request fields:** ignore client-supplied role and landlord scope; never accept `landlord_id` as command authority.
- **Use the intended authorization pair:** resolution requires both the `LANDLORD` role and `PAYMENT_ASSIGN` permission.
- **Use RLS on the normal request session:** do not bypass RLS or substitute the privileged system database connection for this user command.
- **Return only the public read model:** omit internal callback/webhook identifiers from the unassigned-payment list response.
- **Keep real isolation tests:** changes to identity, authorization, or RLS must retain PostgreSQL cross-landlord and forged-claim coverage.

### Why

The route can validate the intended business action while RLS limits visible and writable rows to the trusted landlord context. The request schema cannot override authoritative financial or ownership values.

### Trade-offs and consequences

**Benefits:**
- Forged landlord or role values cannot elevate allocation access.
- Cross-landlord access is checked by both application scope and PostgreSQL policies.

**Costs:**
- A valid identity needs a correctly provisioned active local membership.
- RLS policy and database-role configuration must remain aligned with application routes.

### Revisit when

Membership selection, delegated landlord access, caretaker allocation, or a new database session/role model is introduced. Reassess role policy and RLS together before changing the command.

### Related links

- [Authorization and payment resolution contract](API.md#17-unassigned-payment-api)
- [Security controls and RLS coverage](SECURITY.md)
- [PostgreSQL RLS integration tests](../app/Tests/security/test_postgres_rls.py)

## Decision 5: Record the Full Receipt in the Ledger and Track Application Separately

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

A completed M-Pesa payment is a receipt for the full amount sent. The amount applied to an invoice can be smaller because of a partial payment, an invoice balance, or the absence of an unpaid invoice. The payment allocation and credit records describe application of funds; they are not substitutes for recording the completed receipt.

### Trade-offs considered

1. Write a ledger credit only for the invoice allocation amount: aligns the ledger entry with rent applied, but omits some or all of a completed payment receipt.
2. Write one ledger credit for the full payment amount and record invoice allocation and any excess payment credit separately: preserves the receipt amount and makes application state explicit, but consumers must not treat the full ledger credit as an invoice-paid amount.
3. Write ledger entries for allocation and excess separately: distinguishes application categories, but changes the existing one-payment ledger contract and requires its own uniqueness and reconciliation semantics.

### Decision

For the current M-Pesa payment workflow, create one `CREDIT` ledger entry for the full persisted payment amount. Record the amount applied to an invoice in `payment_allocations`; record excess over an invoice balance or the available amount when no unpaid invoice exists in `payment_credits`. Invoice paid state follows allocated invoice balance, not the full ledger amount.

### Guardrails

- **Ledger records the receipt:** its credit amount is the full persisted payment amount.
- **Allocation records invoice settlement:** calculate invoice paid state from allocations against that invoice, not from ledger credits.
- **Keep unapplied funds distinct:** create `payment_credits` for overpayment or when no unpaid invoice exists; do not count a credit as a second receipt.
- **Keep conservation aligned:** payment consumption includes all extant payment-credit amounts until an explicit domain operation releases that balance.

### Why

The ledger records the completed cash receipt, while allocation and payment-credit records explain how much of that receipt was applied or retained for future use. Keeping those values separate avoids silently reducing the recorded payment when an invoice is only partially paid.

### Trade-offs and consequences

**Benefits:**
- The ledger amount remains equal to the completed payment amount.
- Invoice settlement and unused funds remain visible as separate financial facts.

**Costs:**
- Reports must use allocation amounts for invoice settlement and must not sum the full ledger receipt as rent applied.
- Payment credits retain their original amount; immutable applications record invoice settlement. Refund and cancellation remain separate lifecycle decisions.

### Revisit when

The accounting model adds credit application/release, refunds, reversals, or a revised ledger posting convention. Update the conservation invariants and reporting contract together with any change.

### Related links

- [Allocation and unassigned-payment contract](API.md#17-unassigned-payment-api)
- [Financial security boundary](SECURITY.md#8-financial-security)
- [Resolution integration tests](../app/Tests/security/test_postgres_rls.py)

## Decision 6: Preserve Payments with No Unpaid Invoice as Tenant Credit

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

A completed payment can be linked to a tenant who has no unpaid invoice. The existing allocator recorded the full payment receipt in the ledger and outbox but returned `UNALLOCATED` without a payment allocation or credit row. That left the unapplied balance without a tenant-credit record that a later workflow could reference.

### Trade-offs considered

1. Leave the payment as an unallocated receipt with no credit: preserves current behavior and avoids defining credit use, but the tenant's unapplied balance is not represented as a liability/available balance.
2. Record the full unapplied amount as an `AVAILABLE` payment credit: makes the balance visible and conserved for later use, but requires a follow-up contract for applying, partially applying, refunding, or cancelling credits.
3. Create a placeholder invoice allocation: keeps payment sums attached to an invoice, but falsely represents settlement of an obligation that does not exist.

### Decision

When a completed payment is assigned to a tenant and no unpaid invoice exists, record the remaining available payment amount as an `AVAILABLE` `PaymentCredit` linked to that tenant and source payment. Do not create an invoice allocation or change invoice state. Continue recording the full receipt as one ledger credit and record the outbox event in the same PostgreSQL transaction.

Apply the rule in the existing `InvoiceAllocationService` so matched callback reconciliation and landlord unassigned-payment resolution use the same behavior. Do not create a separate credit or allocation engine.

### Guardrails

- **Preserve payment conservation:** the new credit amount is limited to the payment's persisted amount less prior allocations and extant credits.
- **Preserve invoice truth:** when no eligible invoice exists, do not create an allocation or mark an invoice paid.
- **Preserve receipt accounting:** the ledger credit remains the full receipt amount; the payment credit is an application balance, not a second receipt.
- **Keep the write atomic:** payment allocation/credit, invoice state, ledger, processing/resolution state, and outbox insertion must share the caller's PostgreSQL transaction.
- **Keep one allocator:** matched callbacks and manual resolution must call the existing allocation service.
- **Keep the lifecycle bounded:** automatic invoice application follows Decision 7; refund and cancellation workflows remain unavailable until separately specified.

### Why

An accepted tenant payment with no current rental obligation is still a receipt and the unapplied amount remains owed to or held for that tenant. A payment credit represents that balance without inventing an invoice or treating the receipt as rent already applied.

### Trade-offs and consequences

**Benefits:**
- The payment amount is fully represented by invoice allocations plus payment credits.
- Both matched and manually resolved payments follow one rule for excess or unapplied funds.

**Costs:**
- Reports must distinguish credited funds from amounts applied to invoices.
- The existing credit schema does not record a target invoice or partial-application history, so later credit use needs additional domain and persistence design.

### Revisit when

Requirements change how unapplied receipts are represented, or define refund, cancellation, expiry, or reversal behavior.

### Related links

- [Domain model and accepted rule](DOMAIN.md#accepted-domain-rule-payment-received-with-no-unpaid-invoice)
- [Allocation and unassigned-payment API](API.md#17-unassigned-payment-api)
- [PostgreSQL allocation and resolution tests](../app/Tests/integration/test_webhook_integration.py)

## Decision 7: Automatically Apply Available Credits to Unpaid Invoices

Status: Accepted  
Date: 2026-10-06  
Owners: KodiLedger maintainers

### Context

Decision 6 creates an `AVAILABLE` tenant credit when payment funds have no unpaid invoice. The source credit must remain auditable through later partial applications while payment and invoice balances remain conserved.

### Trade-offs considered

1. Mutate `payment_credits.amount` and status when used: requires little schema work, but loses the original credit amount and cannot explain partial applications or rebuild balances.
2. Add immutable application records: preserves the source amount and gives each invoice application an auditable relationship, but requires a migration, new accounting/read behavior, and more complex concurrency control.
3. Keep credits view-only indefinitely: avoids new financial write paths, but leaves tenant balances unusable for invoice settlement or refunds.

### Decision

Preserve original credits as immutable source balances and represent each application as a separate immutable row linking a credit to an invoice with an amount, timestamp, and idempotency key. Automatically apply available tenant credit in FIFO order to the oldest unpaid invoice when a payment is allocated/resolved and when an invoice is created, up to the remaining invoice balance. Retain any remainder as available. Applications are automatic and do not require landlord selection of an invoice.

Refund and cancellation workflows are not part of this decision and remain unavailable until separately specified.

### Guardrails

- **Never overwrite the original amount:** preserve it as the source receipt application balance.
- **Record every use:** applications identify the invoice; no balance-only decrement without an auditable record.
- **Keep money in scope:** a credit may only apply to an invoice belonging to the same tenant and landlord as the credit.
- **Conserve invoice and credit balances:** application cannot exceed either the remaining credit balance or invoice balance.
- **Lock consistently:** lock source payment transactions, credit rows, then invoices in stable order; test interactions with the existing payment → invoice allocator before release.
- **External refund confirmation:** do not mark a refund complete before the payout is confirmed; provider initiation alone is not settlement.
- **Keep atomic writes:** application records and invoice state commit with the enclosing transaction or roll back.

### Why

Separate immutable records preserve the receipt and its subsequent disposition, support partial use, and allow the available balance to be reconstructed. Automatic application to the oldest unpaid invoice follows the existing payment allocator's invoice ordering and reduces manual selection risk.

### Trade-offs and consequences

**Benefits:**
- Credit balances can be audited and reconstructed from durable records.
- Partial application does not erase the source credit or invoice relationship.
- Invoice settlement can reuse the existing oldest-unpaid invoice rule.

**Costs:**
- Requires an append-only table, migration and RLS policies, reporting changes, and concurrency/rollback coverage.
- Refund, cancellation, expiry, and reversal policies still need separate decisions.

### Revisit when

Product requirements change automatic application order or triggers, or define refund, cancellation, expiry, or tenant-transfer behavior.

### Related links

- [Accepted no-invoice credit rule](#decision-6-preserve-payments-with-no-unpaid-invoice-as-tenant-credit)
- [Domain model and accepted credit application rule](DOMAIN.md#accepted-domain-rule-automatic-application-of-available-credit)
- [Database credit schema](DATABASE.md#6-financial-data-model)
