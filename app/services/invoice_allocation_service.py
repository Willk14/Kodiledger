from decimal import Decimal
from typing import Any
from uuid import UUID

from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_allocation_repository import (
    PaymentAllocationRepository,
)
from app.repositories.payment_credit_repository import (
    PaymentCreditRepository,
)
from app.repositories.payment_transaction_repository import (
    PaymentTransactionRepository,
)
from app.repositories.payment_credit_application_repository import (
    PaymentCreditApplicationRepository,
)
from app.repositories.tenant_repository import TenantRepository


class AllocationConflict(RuntimeError):
    """Persisted allocation state conflicts with a new allocation request."""


class InvoiceAllocationService:
    """Apply persisted payment funds to the oldest unpaid tenant invoice.

    If no unpaid invoice exists, remaining funds are recorded as an available
    payment credit for the tenant rather than being left without an application
    record.

    The tenant row serializes payment allocation, invoice creation, and credit
    use. A payment transaction is then locked before its allocations or credits
    are counted, and the selected invoice is locked last. Keep the
    tenant -> payment -> credit -> invoice order in every caller.

    Allocation and credit writes remain in the caller's transaction; this
    service never commits.
    """

    def __init__(
        self,
        invoice_repository: InvoiceRepository,
        payment_allocation_repository: PaymentAllocationRepository,
        payment_credit_repository: PaymentCreditRepository,
        payment_transaction_repository: PaymentTransactionRepository,
    ) -> None:
        self.invoice_repository = invoice_repository
        self.payment_allocation_repository = payment_allocation_repository
        self.payment_credit_repository = payment_credit_repository
        self.payment_transaction_repository = payment_transaction_repository
        self.tenant_repository = TenantRepository(payment_transaction_repository.db)
        self.credit_applications = PaymentCreditApplicationRepository(
            payment_transaction_repository.db
        )

    async def allocate_payment(
        self,
        *,
        payment_transaction_id: str,
        tenant_id: str,
        payment_amount: Decimal,
    ) -> dict[str, Any]:
        requested_amount = Decimal(str(payment_amount))
        if requested_amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        # Tenant lock serializes new invoices and credit application against
        # incoming payment allocation for this tenant.
        if not await self.tenant_repository.lock_by_id(tenant_id=UUID(tenant_id)):
            raise AllocationConflict("Tenant does not exist.")

        # Payment row serializes allocation/credit consumption for one receipt.
        payment = await self.payment_transaction_repository.get_by_id_for_update(
            payment_transaction_id=payment_transaction_id,
        )
        if payment is None:
            raise ValueError("Payment transaction does not exist.")
        if str(payment.tenant_id) != str(tenant_id):
            raise AllocationConflict(
                "Payment transaction does not belong to the requested tenant."
            )

        persisted_payment_amount = Decimal(str(payment.amount))
        allocated_for_payment = (
            await self.payment_allocation_repository
            .get_total_allocated_for_payment(
                payment_transaction_id=payment_transaction_id,
            )
        )
        credited_for_payment = (
            await self.payment_credit_repository
            .get_total_for_payment_transaction(
                payment_transaction_id=payment_transaction_id,
            )
        )
        already_consumed = allocated_for_payment + credited_for_payment
        if already_consumed > persisted_payment_amount:
            raise AllocationConflict(
                "Persisted allocations and credits exceed the payment amount."
            )

        available_payment_amount = persisted_payment_amount - already_consumed
        amount_to_allocate = min(requested_amount, available_payment_amount)
        if amount_to_allocate <= 0:
            return {
                "status": "UNALLOCATED",
                "reason": "PAYMENT_ALREADY_CONSUMED",
                "payment_transaction_id": payment_transaction_id,
                "payment_amount": persisted_payment_amount,
                "total_allocated_amount": allocated_for_payment,
                "total_credited_amount": credited_for_payment,
                "available_payment_amount": Decimal("0"),
            }

        # The invoice row is locked only after the payment lock above.
        invoice = await self.invoice_repository.get_oldest_unpaid_for_tenant_for_update(
            tenant_id=tenant_id,
        )
        if invoice is None:
            credit = await self.payment_credit_repository.create(
                payment_transaction_id=payment_transaction_id,
                tenant_id=tenant_id,
                amount=amount_to_allocate,
                status="AVAILABLE",
            )
            applications = await self._apply_credit_to_oldest_unpaid_invoices(
                credit_id=str(credit["id"]),
                tenant_id=tenant_id,
                credit_amount=amount_to_allocate,
            )
            applied_amount = sum(
                (Decimal(str(row["amount"])) for row in applications),
                Decimal("0"),
            )
            remaining_credit = amount_to_allocate - applied_amount
            if remaining_credit == 0:
                await self.payment_credit_repository.mark_applied(
                    payment_credit_id=str(credit["id"])
                )
            return {
                "status": "UNALLOCATED",
                "reason": "NO_UNPAID_INVOICE",
                "payment_transaction_id": payment_transaction_id,
                "payment_amount": persisted_payment_amount,
                "total_allocated_amount": allocated_for_payment,
                "total_credited_amount": credited_for_payment + amount_to_allocate,
                "available_payment_amount": Decimal("0"),
                "credited_amount": remaining_credit,
                "credit_applied_amount": applied_amount,
                "payment_credit_id": str(credit["id"]),
            }

        invoice_id = str(invoice["id"])
        invoice_number = invoice["invoice_number"]
        invoice_amount = Decimal(str(invoice["total_amount"]))

        # This must be a separate statement after acquiring the invoice lock.
        allocated_for_invoice = Decimal(
            str(
                await self.invoice_repository.get_allocated_amount(
                    invoice_id=invoice_id,
                )
            )
        )

        existing = await self.payment_allocation_repository.get(
            payment_transaction_id=payment_transaction_id,
            invoice_id=invoice_id,
        )
        if existing is not None:
            return self._duplicate_result(
                existing=existing,
                invoice=invoice,
                invoice_amount=invoice_amount,
                allocated_for_invoice=allocated_for_invoice,
            )

        remaining_invoice_amount = invoice_amount - allocated_for_invoice
        if remaining_invoice_amount <= 0:
            await self.invoice_repository.mark_paid(invoice_id=invoice_id)
            return {
                "status": "UNALLOCATED",
                "reason": "INVOICE_ALREADY_FULLY_ALLOCATED",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
            }

        allocated_amount = min(amount_to_allocate, remaining_invoice_amount)
        excess_amount = amount_to_allocate - allocated_amount

        allocation = await self.payment_allocation_repository.create(
            payment_transaction_id=payment_transaction_id,
            invoice_id=invoice_id,
            amount=allocated_amount,
            status="ALLOCATED",
        )
        if allocation is None:
            # The unique pair constraint is the final guard for writers that
            # do not follow the payment-row lock protocol.
            existing = await self.payment_allocation_repository.get(
                payment_transaction_id=payment_transaction_id,
                invoice_id=invoice_id,
            )
            if existing is None:
                raise RuntimeError(
                    "Allocation conflicted but the existing row was not found."
                )
            return self._duplicate_result(
                existing=existing,
                invoice=invoice,
                invoice_amount=invoice_amount,
                allocated_for_invoice=allocated_for_invoice,
            )

        new_allocated_for_invoice = allocated_for_invoice + allocated_amount
        new_remaining_invoice_amount = (
            invoice_amount - new_allocated_for_invoice
        )

        if excess_amount > 0:
            credit = await self.payment_credit_repository.create(
                payment_transaction_id=payment_transaction_id,
                tenant_id=tenant_id,
                amount=excess_amount,
                status="AVAILABLE",
            )
            credit_applications = await self._apply_credit_to_oldest_unpaid_invoices(
                credit_id=str(credit["id"]),
                tenant_id=tenant_id,
                credit_amount=excess_amount,
            )
            credit_applied_amount = sum(
                (Decimal(str(row["amount"])) for row in credit_applications),
                Decimal("0"),
            )
            remaining_credit = excess_amount - credit_applied_amount
            if remaining_credit == 0:
                await self.payment_credit_repository.mark_applied(
                    payment_credit_id=str(credit["id"])
                )
            await self.invoice_repository.mark_paid(invoice_id=invoice_id)
            return {
                "status": "OVERPAYMENT_CREDITED",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "invoice_amount": invoice_amount,
                "previously_allocated_amount": allocated_for_invoice,
                "allocated_amount": allocated_amount,
                "total_allocated_amount": new_allocated_for_invoice,
                "remaining_invoice_amount": Decimal("0"),
                "payment_amount": amount_to_allocate,
                "excess_amount": excess_amount,
                "credit_applied_amount": credit_applied_amount,
                "remaining_credit_amount": remaining_credit,
                "payment_allocation_id": str(allocation["id"]),
                "payment_credit_id": str(credit["id"]),
                "invoice_paid": True,
            }

        invoice_paid = new_remaining_invoice_amount == 0
        if invoice_paid:
            await self.invoice_repository.mark_paid(invoice_id=invoice_id)

        return {
            "status": "ALLOCATED" if invoice_paid else "PARTIALLY_ALLOCATED",
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "invoice_amount": invoice_amount,
            "previously_allocated_amount": allocated_for_invoice,
            "allocated_amount": allocated_amount,
            "total_allocated_amount": new_allocated_for_invoice,
            "remaining_invoice_amount": new_remaining_invoice_amount,
            "payment_allocation_id": str(allocation["id"]),
            "invoice_paid": invoice_paid,
        }

    async def apply_available_credits_for_new_invoice(
        self,
        *,
        invoice_id: str,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Apply existing credits to a newly created invoice in FIFO order.

        The caller must hold the tenant row lock and the invoice creation
        transaction. Credit rows and then eligible invoice rows are locked in
        deterministic FIFO order.
        """
        credits = await self.payment_credit_repository.list_available_for_tenant_for_update(
            tenant_id=tenant_id
        )
        if not credits:
            return []
        new_invoice = await self.invoice_repository.get_by_id_for_update(
            invoice_id=invoice_id
        )
        if new_invoice is None or str(new_invoice["tenant_id"]) != tenant_id:
            raise AllocationConflict("Invoice does not belong to this tenant.")
        applied: list[dict[str, Any]] = []
        for credit in credits:
            consumed = await self.credit_applications.get_total_for_credit(
                payment_credit_id=credit["id"]
            )
            credit_remaining = Decimal(str(credit["amount"])) - consumed
            if credit_remaining <= 0:
                await self.payment_credit_repository.mark_applied(
                    payment_credit_id=credit["id"]
                )
                continue
            while credit_remaining > 0:
                invoice = await self.invoice_repository.get_oldest_unpaid_for_tenant_for_update(
                    tenant_id=tenant_id
                )
                if invoice is None:
                    break
                current_invoice_id = str(invoice["id"])
                invoice_remaining = Decimal(str(invoice["total_amount"])) - Decimal(
                    str(await self.invoice_repository.get_allocated_amount(
                        invoice_id=current_invoice_id
                    ))
                )
                if invoice_remaining <= 0:
                    await self.invoice_repository.mark_paid(
                        invoice_id=current_invoice_id
                    )
                    continue
                amount = min(credit_remaining, invoice_remaining)
                application = await self.credit_applications.create(
                    payment_credit_id=credit["id"],
                    invoice_id=current_invoice_id,
                    amount=amount,
                    application_key=(
                        f"CREDIT:{credit['id']}:INVOICE:{current_invoice_id}"
                    ),
                )
                if application is None:
                    break
                applied.append({
                    "payment_credit_id": credit["id"],
                    "invoice_id": current_invoice_id,
                    "amount": amount,
                })
                credit_remaining -= amount
                if amount == invoice_remaining:
                    await self.invoice_repository.mark_paid(
                        invoice_id=current_invoice_id
                    )
            if credit_remaining == 0:
                await self.payment_credit_repository.mark_applied(
                    payment_credit_id=credit["id"]
                )
        return applied

    async def _apply_credit_to_oldest_unpaid_invoices(
        self,
        *,
        credit_id: str,
        tenant_id: str,
        credit_amount: Decimal,
    ) -> list[dict[str, Any]]:
        remaining = Decimal(str(credit_amount))
        applications: list[dict[str, Any]] = []
        while remaining > 0:
            invoice = await self.invoice_repository.get_oldest_unpaid_for_tenant_for_update(
                tenant_id=tenant_id
            )
            if invoice is None:
                break
            invoice_id = str(invoice["id"])
            invoice_balance = Decimal(str(invoice["total_amount"])) - Decimal(
                str(await self.invoice_repository.get_allocated_amount(invoice_id=invoice_id))
            )
            if invoice_balance <= 0:
                await self.invoice_repository.mark_paid(invoice_id=invoice_id)
                continue
            amount = min(remaining, invoice_balance)
            application = await self.credit_applications.create(
                payment_credit_id=credit_id,
                invoice_id=invoice_id,
                amount=amount,
                application_key=f"CREDIT:{credit_id}:INVOICE:{invoice_id}",
            )
            if application is None:
                break
            applications.append({"invoice_id": invoice_id, "amount": amount})
            remaining -= amount
            if amount == invoice_balance:
                await self.invoice_repository.mark_paid(invoice_id=invoice_id)
        return applications

    @staticmethod
    def _duplicate_result(
        *,
        existing: dict[str, Any],
        invoice: dict[str, Any],
        invoice_amount: Decimal,
        allocated_for_invoice: Decimal,
    ) -> dict[str, Any]:
        """Return an existing ALLOCATED pair without repeating side effects.

        The schema permits only one row per payment/invoice pair. Returning
        that row preserves a stable service result for a retry while ensuring
        a uniqueness conflict cannot create another credit or invoice
        transition. The caller still owns the surrounding transaction.
        """
        if str(existing["status"]) != "ALLOCATED":
            raise AllocationConflict(
                "The payment/invoice pair already exists in a reversed state."
            )

        return {
            "status": "ALREADY_ALLOCATED",
            "reason": "PAYMENT_INVOICE_PAIR_EXISTS",
            "invoice_id": str(invoice["id"]),
            "invoice_number": invoice["invoice_number"],
            "invoice_amount": invoice_amount,
            "previously_allocated_amount": allocated_for_invoice,
            "allocated_amount": Decimal(str(existing["amount"])),
            "total_allocated_amount": allocated_for_invoice,
            "remaining_invoice_amount": max(
                invoice_amount - allocated_for_invoice,
                Decimal("0"),
            ),
            "payment_allocation_id": str(existing["id"]),
            "invoice_paid": bool(invoice["is_paid"]),
        }
