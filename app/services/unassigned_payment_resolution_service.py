from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.ledger_repository import LedgerRepository
from app.repositories.outbox_event_repository import OutboxEventRepository
from app.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.repositories.payment_credit_repository import PaymentCreditRepository
from app.repositories.payment_processing_repository import PaymentProcessingRepository
from app.repositories.payment_transaction_repository import PaymentTransactionRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.unassigned_payment_repository import UnassignedPaymentRepository
from app.services.invoice_allocation_service import InvoiceAllocationService
from app.services.outbox_event_service import OutboxEventService


class UnassignedPaymentNotFound(Exception):
    """No unassigned payment exists in the caller's landlord scope."""


class ResolutionConflict(Exception):
    """The payment is resolved already or its financial data is inconsistent."""


class UnassignedPaymentResolutionService:
    """Resolve an unmatched receipt as one landlord-scoped DB transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.unassigned = UnassignedPaymentRepository(db)
        self.tenants = TenantRepository(db)
        self.transactions = PaymentTransactionRepository(db)
        self.processing = PaymentProcessingRepository(db)
        self.ledger = LedgerRepository(db)
        self.outbox = OutboxEventService(OutboxEventRepository(db))
        self.allocation = InvoiceAllocationService(
            invoice_repository=InvoiceRepository(db),
            payment_allocation_repository=PaymentAllocationRepository(db),
            payment_credit_repository=PaymentCreditRepository(db),
            payment_transaction_repository=self.transactions,
        )

    async def list_unresolved(self, *, landlord_id: UUID) -> list[dict[str, Any]]:
        return await self.unassigned.list_unresolved(str(landlord_id))

    async def resolve(
        self,
        *,
        payment_id: UUID,
        landlord_id: UUID,
        tenant_id: UUID,
        resolved_by_user_id: UUID,
    ) -> dict[str, Any]:
        payment = await self.unassigned.get_by_id_for_update(
            payment_id=str(payment_id),
            landlord_id=str(landlord_id),
        )
        if payment is None:
            raise UnassignedPaymentNotFound
        if payment["is_resolved"] is True:
            raise ResolutionConflict("Unassigned payment has already been resolved.")

        tenant = await self.tenants.get_active_scope_by_id_and_landlord(
            tenant_id=tenant_id,
            landlord_id=landlord_id,
        )
        if tenant is None:
            raise UnassignedPaymentNotFound

        receipt = payment["mpesa_receipt_number"]
        amount = Decimal(str(payment["amount"]))
        transaction = await self.transactions.get_by_receipt_for_update(
            mpesa_receipt_number=receipt,
            landlord_id=str(landlord_id),
        )
        if transaction is None:
            # Supports legacy unassigned rows that predate normalized
            # payment_transactions. The insert remains in this transaction.
            created = await self.transactions.create(
                landlord_id=str(landlord_id),
                tenant_id=None,
                raw_webhook_id=(
                    str(payment["raw_webhook_id"])
                    if payment["raw_webhook_id"] is not None
                    else None
                ),
                merchant_request_id=None,
                checkout_request_id=None,
                mpesa_receipt_number=receipt,
                payer_phone=payment["payer_phone"],
                payer_name=payment["payer_name"],
                amount=amount,
                payment_method="MPESA_STK_PUSH",
                status="COMPLETED",
            )
            transaction = await self.transactions.get_by_receipt_for_update(
                mpesa_receipt_number=receipt,
                landlord_id=str(landlord_id),
            )
            if transaction is None or str(transaction.id) != str(created["id"]):
                raise ResolutionConflict("Payment transaction changed during resolution.")

        if (
            transaction.tenant_id is not None
            or transaction.status != "COMPLETED"
            or transaction.amount != amount
        ):
            raise ResolutionConflict("Payment transaction does not match the unresolved receipt.")
        if await self.ledger.get_by_receipt(receipt) is not None:
            raise ResolutionConflict("A ledger entry already exists for this unresolved receipt.")

        transaction.tenant_id = tenant_id
        await self.db.flush()

        allocation = await self.allocation.allocate_payment(
            payment_transaction_id=str(transaction.id),
            tenant_id=str(tenant_id),
            payment_amount=amount,
        )

        await self.ledger.create_credit(
            landlord_id=str(landlord_id),
            unit_id=str(tenant["unit_id"]),
            tenant_id=str(tenant_id),
            mpesa_receipt=receipt,
            merchant_request_id=transaction.merchant_request_id,
            payment_transaction_id=str(transaction.id),
            amount=amount,
            phone=payment["payer_phone"],
            account_ref=payment["invalid_account_reference"],
            description=(
                f"M-Pesa STK Push Payment - Receipt: {receipt}"
            ),
        )
        outbox_event = await self.outbox.record_payment_processed(
            payment_transaction_id=str(transaction.id),
            payment_receipt=receipt,
            amount=amount,
            tenant_id=str(tenant_id),
            landlord_id=str(landlord_id),
            allocation=allocation,
        )
        await self.processing.mark_assigned(
            receipt=receipt,
            landlord_id=str(landlord_id),
        )
        resolved = await self.unassigned.mark_resolved(
            payment_id=str(payment_id),
            landlord_id=str(landlord_id),
            unit_id=str(tenant["unit_id"]),
            resolved_by_user_id=str(resolved_by_user_id),
        )
        if resolved is None:
            raise ResolutionConflict("Unassigned payment resolution was already applied.")

        return {
            "id": payment_id,
            "payment_transaction_id": transaction.id,
            "mpesa_receipt_number": receipt,
            "tenant_id": tenant_id,
            "unit_id": tenant["unit_id"],
            "amount": amount,
            "allocation": allocation,
            "outbox_event_id": outbox_event["id"],
            "resolved_at": resolved["resolved_at"],
        }
