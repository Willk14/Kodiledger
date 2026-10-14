from __future__ import annotations

from uuid import UUID

from app.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.repositories.payment_credit_repository import PaymentCreditRepository
from app.repositories.payment_transaction_repository import PaymentTransactionRepository
from app.repositories.tenant_repository import TenantRepository
from app.models.invoice import Invoice
from app.repositories.invoice_repository import InvoiceRepository
from app.services.invoice_allocation_service import InvoiceAllocationService


class InvoiceService:
    def __init__(self, repository: InvoiceRepository) -> None:
        self.repository = repository
        self.tenants = TenantRepository(repository.db)
        self.allocation = InvoiceAllocationService(
            invoice_repository=repository,
            payment_allocation_repository=PaymentAllocationRepository(repository.db),
            payment_credit_repository=PaymentCreditRepository(repository.db),
            payment_transaction_repository=PaymentTransactionRepository(repository.db),
        )

    async def list_for_landlord(self, landlord_id: UUID) -> list[Invoice]:
        return await self.repository.list_by_landlord(str(landlord_id))

    async def get_for_landlord(
        self,
        invoice_id: UUID,
        landlord_id: UUID,
    ) -> Invoice | None:
        return await self.repository.get_by_id_and_landlord(
            invoice_id=str(invoice_id),
            landlord_id=str(landlord_id),
        )

    async def create(
        self,
        *,
        landlord_id: UUID,
        values: dict[str, object],
    ) -> Invoice | None:
        invoice_values = dict(values)
        unit_id = str(invoice_values.pop("unit_id"))
        tenant_id = str(invoice_values.pop("tenant_id"))
        landlord_scope = str(landlord_id)

        if not await self.repository.unit_belongs_to_landlord(
            unit_id=unit_id,
            landlord_id=landlord_scope,
        ):
            return None
        if not await self.repository.tenant_belongs_to_unit_and_landlord(
            tenant_id=tenant_id,
            unit_id=unit_id,
            landlord_id=landlord_scope,
        ):
            return None

        # Serialize invoice creation against incoming payments and credit
        # application for this tenant. Lock order starts with the tenant.
        if not await self.tenants.lock_by_id(tenant_id=UUID(tenant_id)):
            return None

        invoice = await self.repository.create(
            landlord_id=landlord_scope,
            values={
                **invoice_values,
                "unit_id": UUID(unit_id),
                "tenant_id": UUID(tenant_id),
            },
        )
        await self.allocation.apply_available_credits_for_new_invoice(
            invoice_id=str(invoice.id),
            tenant_id=tenant_id,
        )
        await self.repository.db.refresh(invoice)
        return invoice
