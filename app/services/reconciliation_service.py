from __future__ import annotations

from decimal import Decimal

from app.repositories.ledger_repository import LedgerRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.unassigned_payment_repository import (
    UnassignedPaymentRepository,
)
from app.repositories.payment_transaction_repository import (
    PaymentTransactionRepository,
)
from app.services.invoice_allocation_service import (
    InvoiceAllocationService,
)
from app.services.outbox_event_service import OutboxEventService


class ReconciliationService:
    """
    Business logic for reconciling successful M-Pesa payments.

    Flow:

        successful payment
                |
                v
        create payment_transaction
                |
                v
             find tenant
             /        \
          FOUND      NOT FOUND
            |             |
            v             v
      invoice allocation  unassigned
            |
            v
       ledger CREDIT
            |
            v
       outbox event
    """

    def __init__(
        self,
        tenant_repository: TenantRepository,
        payment_transaction_repository: PaymentTransactionRepository,
        invoice_allocation_service: InvoiceAllocationService,
        ledger_repository: LedgerRepository,
        unassigned_payment_repository: UnassignedPaymentRepository,
        outbox_event_service: OutboxEventService,
    ) -> None:
        self.tenant_repository = tenant_repository
        self.payment_transaction_repository = (
            payment_transaction_repository
        )
        self.invoice_allocation_service = (
            invoice_allocation_service
        )
        self.ledger_repository = ledger_repository
        self.unassigned_payment_repository = (
            unassigned_payment_repository
        )
        self.outbox_event_service = outbox_event_service

    async def reconcile_payment(
        self,
        mpesa_receipt: str,
        amount: Decimal,
        phone: str,
        landlord_id: str,
        raw_webhook_id: str,
        merchant_request_id: str,
        checkout_request_id: str | None = None,
        account_ref: str | None = None,
        payer_name: str | None = None,
    ) -> dict:
        """
        Reconcile a successful M-Pesa payment.

        A normalized payment transaction is created first.

        A matched tenant is then checked for an unpaid invoice.

        Payments may be fully allocated, partially allocated,
        or may create an available payment credit when the
        payment exceeds the outstanding invoice balance.

        For matched payments, the ledger entry and outbox event
        are created in the same database transaction as the
        payment reconciliation.
        """

        # ========================================================
        # 1. Find tenant
        # ========================================================

        tenant = await self.tenant_repository.get_active_by_phone(
            phone=phone,
            landlord_id=landlord_id,
        )

        tenant_id = str(tenant["id"]) if tenant else None

        # ========================================================
        # 2. Create normalized payment transaction
        # ========================================================

        payment_transaction = (
            await self.payment_transaction_repository.create(
                landlord_id=landlord_id,
                tenant_id=tenant_id,
                raw_webhook_id=raw_webhook_id,
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                mpesa_receipt_number=mpesa_receipt,
                payer_phone=phone,
                payer_name=payer_name,
                amount=amount,
                payment_method="MPESA_STK_PUSH",
                status="COMPLETED",
            )
        )

        payment_transaction_id = str(
            payment_transaction["id"]
        )

        # ========================================================
        # 3. No matching tenant
        # ========================================================

        if tenant is None:
            await self.unassigned_payment_repository.create(
                landlord_id=landlord_id,
                raw_webhook_id=raw_webhook_id,
                mpesa_receipt=mpesa_receipt,
                amount=amount,
                payer_phone=phone,
                account_reference=account_ref,
            )

            return {
                "status": "UNASSIGNED",
                "mpesa_receipt": mpesa_receipt,
                "merchant_request_id": merchant_request_id,
                "payment_transaction_id": payment_transaction_id,
            }

        # ========================================================
        # 4. Allocate payment to invoice
        # ========================================================

        allocation = (
            await self.invoice_allocation_service.allocate_payment(
                payment_transaction_id=payment_transaction_id,
                tenant_id=tenant_id,
                payment_amount=amount,
            )
        )

        # ========================================================
        # 5. Record ledger accounting effect
        # ========================================================

        await self.ledger_repository.create_credit(
            landlord_id=landlord_id,
            unit_id=str(tenant["unit_id"]),
            tenant_id=str(tenant["id"]),
            mpesa_receipt=mpesa_receipt,
            merchant_request_id=merchant_request_id,
            payment_transaction_id=payment_transaction_id,
            amount=amount,
            phone=phone,
            account_ref=account_ref,
        )

        # ========================================================
        # 6. Record transactional outbox event
        # ========================================================

        outbox_event = (
            await self.outbox_event_service.record_payment_processed(
                payment_transaction_id=payment_transaction_id,
                payment_receipt=mpesa_receipt,
                amount=amount,
                tenant_id=str(tenant["id"]),
                landlord_id=landlord_id,
                allocation=allocation,
            )
        )

        # ========================================================
        # 7. Return reconciliation result
        # ========================================================

        return {
            "status": "MATCHED",
            "mpesa_receipt": mpesa_receipt,
            "merchant_request_id": merchant_request_id,
            "tenant_id": str(tenant["id"]),
            "unit_id": str(tenant["unit_id"]),
            "payment_transaction_id": payment_transaction_id,
            "allocation": allocation,
            "outbox_event_id": str(outbox_event["id"]),
        }