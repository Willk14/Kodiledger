from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.landlord_repository import LandlordRepository
from app.repositories.ledger_repository import LedgerRepository
from app.repositories.outbox_event_repository import OutboxEventRepository
from app.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.repositories.payment_credit_repository import PaymentCreditRepository
from app.repositories.payment_processing_repository import PaymentProcessingRepository
from app.repositories.payment_transaction_repository import PaymentTransactionRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.unassigned_payment_repository import UnassignedPaymentRepository
from app.repositories.webhook_repository import WebhookRepository
from app.schemas.mpesa import MpesaStkPushCallbackPayload
from app.services.idempotency_service import IdempotencyService
from app.services.invoice_allocation_service import InvoiceAllocationService
from app.services.outbox_event_service import OutboxEventService
from app.services.reconciliation_service import ReconciliationService
from app.services.webhook_service import WebhookService


class WebhookReplayWorker:
    """Retries durable successful callbacks whose financial transaction failed."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], batch_size: int = 50):
        self.session_factory = session_factory
        self.batch_size = batch_size

    async def run_once(self) -> int:
        async with self.session_factory() as db:
            inbox = WebhookRepository(db)
            events = await inbox.claim_pending(self.batch_size)
            await db.commit()

        processed = 0
        for event in events:
            async with self.session_factory() as db:
                service = self._service(db)
                result = await service.process_mpesa_callback(
                    MpesaStkPushCallbackPayload.model_validate(event["raw_payload"]),
                    db,
                    raw_webhook_id=str(event["id"]),
                    persist_inbox=False,
                    retry_delay_seconds=self.retry_delay(event["attempt_count"] + 1),
                )
                if result.get("ResultCode") == 0:
                    processed += 1
        return processed

    @staticmethod
    def retry_delay(attempt: int) -> int:
        return min(30 * (2 ** max(attempt - 1, 0)), 300)

    @staticmethod
    def _service(db: AsyncSession) -> WebhookService:
        webhook = WebhookRepository(db)
        landlord = LandlordRepository(db)
        processing = PaymentProcessingRepository(db)
        tenants = TenantRepository(db)
        transactions = PaymentTransactionRepository(db)
        allocations = PaymentAllocationRepository(db)
        invoices = InvoiceRepository(db)
        credits = PaymentCreditRepository(db)
        ledger = LedgerRepository(db)
        unassigned = UnassignedPaymentRepository(db)
        outbox = OutboxEventService(OutboxEventRepository(db))
        allocation_service = InvoiceAllocationService(
            invoice_repository=invoices,
            payment_allocation_repository=allocations,
            payment_credit_repository=credits,
            payment_transaction_repository=transactions,
        )
        reconciliation = ReconciliationService(
            tenant_repository=tenants,
            payment_transaction_repository=transactions,
            invoice_allocation_service=allocation_service,
            ledger_repository=ledger,
            unassigned_payment_repository=unassigned,
            outbox_event_service=outbox,
        )
        return WebhookService(
            webhook_repository=webhook,
            landlord_repository=landlord,
            payment_processing_repository=processing,
            idempotency_service=IdempotencyService(),
            reconciliation_service=reconciliation,
        )
