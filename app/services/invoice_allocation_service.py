from decimal import Decimal
from typing import Any

from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_allocation_repository import (
    PaymentAllocationRepository,
)
from app.repositories.payment_credit_repository import (
    PaymentCreditRepository,
)


class InvoiceAllocationService:
    """
    Concurrency-safe invoice allocation.

    The invoice row is locked first. The current allocation total is then
    calculated in a separate SQL statement while that lock is held.

    Payment rules:
    - payment <= remaining balance:
        allocate the full payment
    - payment == remaining balance:
        fully settle the invoice
    - payment > remaining balance:
        allocate the remaining balance and create a tenant credit
        for the excess
    """

    def __init__(
        self,
        invoice_repository: InvoiceRepository,
        payment_allocation_repository: PaymentAllocationRepository,
        payment_credit_repository: PaymentCreditRepository,
    ) -> None:
        self.invoice_repository = invoice_repository
        self.payment_allocation_repository = payment_allocation_repository
        self.payment_credit_repository = payment_credit_repository

    async def allocate_payment(
        self,
        *,
        payment_transaction_id: str,
        tenant_id: str,
        payment_amount: Decimal,
    ) -> dict[str, Any]:

        if payment_amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        # 1. Find and lock the candidate invoice.
        invoice = (
            await self.invoice_repository
            .get_oldest_unpaid_for_tenant_for_update(
                tenant_id=tenant_id,
            )
        )

        if invoice is None:
            return {
                "status": "UNALLOCATED",
                "reason": "NO_UNPAID_INVOICE",
            }

        invoice_id = str(invoice["id"])
        invoice_number = invoice["invoice_number"]

        # 2. IMPORTANT:
        # Calculate allocations in a NEW SQL statement after the invoice
        # lock has been acquired.
        allocated_amount = Decimal(
            str(
                await self.invoice_repository.get_allocated_amount(
                    invoice_id=invoice_id,
                )
            )
        )

        invoice_amount = Decimal(str(invoice["total_amount"]))
        remaining_amount = invoice_amount - allocated_amount

        # Defensive protection.
        if remaining_amount <= 0:
            await self.invoice_repository.mark_paid(
                invoice_id=invoice_id,
            )

            return {
                "status": "UNALLOCATED",
                "reason": "INVOICE_ALREADY_FULLY_ALLOCATED",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
            }

        # ------------------------------------------------------------
        # NORMAL PAYMENT / PARTIAL PAYMENT
        # ------------------------------------------------------------
        if payment_amount <= remaining_amount:

            allocation = await self.payment_allocation_repository.create(
                payment_transaction_id=payment_transaction_id,
                invoice_id=invoice_id,
                amount=payment_amount,
                status="ALLOCATED",
            )

            new_allocated_amount = allocated_amount + payment_amount
            new_remaining_amount = (
                invoice_amount - new_allocated_amount
            )

            if new_remaining_amount == 0:
                await self.invoice_repository.mark_paid(
                    invoice_id=invoice_id,
                )

                allocation_status = "ALLOCATED"
                invoice_paid = True
            else:
                allocation_status = "PARTIALLY_ALLOCATED"
                invoice_paid = False

            return {
                "status": allocation_status,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "invoice_amount": invoice_amount,
                "previously_allocated_amount": allocated_amount,
                "allocated_amount": payment_amount,
                "total_allocated_amount": new_allocated_amount,
                "remaining_invoice_amount": new_remaining_amount,
                "payment_allocation_id": str(allocation["id"]),
                "invoice_paid": invoice_paid,
            }

        # ------------------------------------------------------------
        # OVERPAYMENT
        # ------------------------------------------------------------
        invoice_payment = remaining_amount
        excess_amount = payment_amount - remaining_amount

        allocation = await self.payment_allocation_repository.create(
            payment_transaction_id=payment_transaction_id,
            invoice_id=invoice_id,
            amount=invoice_payment,
            status="ALLOCATED",
        )

        credit = await self.payment_credit_repository.create(
            payment_transaction_id=payment_transaction_id,
            tenant_id=tenant_id,
            amount=excess_amount,
            status="AVAILABLE",
        )

        await self.invoice_repository.mark_paid(
            invoice_id=invoice_id,
        )

        return {
            "status": "OVERPAYMENT_CREDITED",
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "invoice_amount": invoice_amount,
            "previously_allocated_amount": allocated_amount,
            "allocated_amount": invoice_payment,
            "total_allocated_amount": invoice_amount,
            "remaining_invoice_amount": Decimal("0"),
            "payment_amount": payment_amount,
            "excess_amount": excess_amount,
            "payment_allocation_id": str(allocation["id"]),
            "payment_credit_id": str(credit["id"]),
            "invoice_paid": True,
        }