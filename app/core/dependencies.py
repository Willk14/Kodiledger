from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.repositories.landlord_repository import LandlordRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.webhook_repository import WebhookRepository
from app.repositories.payment_processing_repository import (
    PaymentProcessingRepository,
)
from app.repositories.ledger_repository import LedgerRepository
from app.repositories.unassigned_payment_repository import (
    UnassignedPaymentRepository,
)
from app.repositories.payment_transaction_repository import (
    PaymentTransactionRepository,
)
from app.repositories.payment_allocation_repository import (
    PaymentAllocationRepository,
)
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_credit_repository import (
    PaymentCreditRepository,
)
from app.repositories.outbox_event_repository import (
    OutboxEventRepository,
)

from app.services.idempotency_service import IdempotencyService
from app.services.invoice_allocation_service import (
    InvoiceAllocationService,
)
from app.services.reconciliation_service import ReconciliationService
from app.services.webhook_service import WebhookService
from app.services.outbox_event_service import OutboxEventService


# ============================================================
# Repository dependencies
# ============================================================

def get_landlord_repository(
    db: AsyncSession = Depends(get_db),
) -> LandlordRepository:
    return LandlordRepository(db)


def get_tenant_repository(
    db: AsyncSession = Depends(get_db),
) -> TenantRepository:
    return TenantRepository(db)


def get_webhook_repository(
    db: AsyncSession = Depends(get_db),
) -> WebhookRepository:
    return WebhookRepository(db)


def get_payment_processing_repository(
    db: AsyncSession = Depends(get_db),
) -> PaymentProcessingRepository:
    return PaymentProcessingRepository(db)


def get_ledger_repository(
    db: AsyncSession = Depends(get_db),
) -> LedgerRepository:
    return LedgerRepository(db)


def get_unassigned_payment_repository(
    db: AsyncSession = Depends(get_db),
) -> UnassignedPaymentRepository:
    return UnassignedPaymentRepository(db)


def get_payment_transaction_repository(
    db: AsyncSession = Depends(get_db),
) -> PaymentTransactionRepository:
    return PaymentTransactionRepository(db)


def get_payment_allocation_repository(
    db: AsyncSession = Depends(get_db),
) -> PaymentAllocationRepository:
    return PaymentAllocationRepository(db)


def get_invoice_repository(
    db: AsyncSession = Depends(get_db),
) -> InvoiceRepository:
    return InvoiceRepository(db)


def get_payment_credit_repository(
    db: AsyncSession = Depends(get_db),
) -> PaymentCreditRepository:
    return PaymentCreditRepository(db)


def get_outbox_event_repository(
    db: AsyncSession = Depends(get_db),
) -> OutboxEventRepository:
    return OutboxEventRepository(db)


# ============================================================
# Service dependencies
# ============================================================

def get_idempotency_service() -> IdempotencyService:
    return IdempotencyService()


def get_outbox_event_service(
    repository: OutboxEventRepository = Depends(
        get_outbox_event_repository
    ),
) -> OutboxEventService:
    return OutboxEventService(repository)


def get_invoice_allocation_service(
    invoice_repository: InvoiceRepository = Depends(
        get_invoice_repository
    ),
    payment_allocation_repository: PaymentAllocationRepository = Depends(
        get_payment_allocation_repository
    ),
    payment_credit_repository: PaymentCreditRepository = Depends(
        get_payment_credit_repository
    ),
) -> InvoiceAllocationService:
    return InvoiceAllocationService(
        invoice_repository=invoice_repository,
        payment_allocation_repository=payment_allocation_repository,
        payment_credit_repository=payment_credit_repository,
    )


def get_reconciliation_service(
    tenant_repository: TenantRepository = Depends(
        get_tenant_repository
    ),
    payment_transaction_repository: PaymentTransactionRepository = Depends(
        get_payment_transaction_repository
    ),
    invoice_allocation_service: InvoiceAllocationService = Depends(
        get_invoice_allocation_service
    ),
    ledger_repository: LedgerRepository = Depends(
        get_ledger_repository
    ),
    unassigned_payment_repository: UnassignedPaymentRepository = Depends(
        get_unassigned_payment_repository
    ),
    outbox_event_service: OutboxEventService = Depends(
        get_outbox_event_service
    ),
) -> ReconciliationService:
    return ReconciliationService(
        tenant_repository=tenant_repository,
        payment_transaction_repository=payment_transaction_repository,
        invoice_allocation_service=invoice_allocation_service,
        ledger_repository=ledger_repository,
        unassigned_payment_repository=unassigned_payment_repository,
        outbox_event_service=outbox_event_service,
    )


def get_webhook_service(
    webhook_repository: WebhookRepository = Depends(
        get_webhook_repository
    ),
    landlord_repository: LandlordRepository = Depends(
        get_landlord_repository
    ),
    payment_processing_repository: PaymentProcessingRepository = Depends(
        get_payment_processing_repository
    ),
    idempotency_service: IdempotencyService = Depends(
        get_idempotency_service
    ),
    reconciliation_service: ReconciliationService = Depends(
        get_reconciliation_service
    ),
) -> WebhookService:
    return WebhookService(
        webhook_repository=webhook_repository,
        landlord_repository=landlord_repository,
        payment_processing_repository=payment_processing_repository,
        idempotency_service=idempotency_service,
        reconciliation_service=reconciliation_service,
    )