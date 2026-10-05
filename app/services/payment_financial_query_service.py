from __future__ import annotations

from uuid import UUID

from app.models.payment_allocation import PaymentAllocation
from app.models.payment_credit import PaymentCredit
from app.models.payment_transaction import PaymentTransaction
from app.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.repositories.payment_credit_repository import PaymentCreditRepository
from app.repositories.payment_transaction_repository import PaymentTransactionRepository


class PaymentFinancialQueryService:
    """Read allocation and credit records for an authorized payment."""

    def __init__(
        self,
        payment_repository: PaymentTransactionRepository,
        allocation_repository: PaymentAllocationRepository,
        credit_repository: PaymentCreditRepository,
    ) -> None:
        self.payment_repository = payment_repository
        self.allocation_repository = allocation_repository
        self.credit_repository = credit_repository

    async def list_allocations(
        self,
        *,
        payment_id: UUID,
        landlord_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[PaymentAllocation] | None:
        payment = await self._get_payment(
            payment_id=payment_id,
            landlord_id=landlord_id,
            tenant_id=tenant_id,
        )
        if payment is None:
            return None
        return await self.allocation_repository.list_for_payment_transaction(
            payment_transaction_id=str(payment_id),
            landlord_id=str(landlord_id),
        )

    async def list_credits(
        self,
        *,
        payment_id: UUID,
        landlord_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[PaymentCredit] | None:
        payment = await self._get_payment(
            payment_id=payment_id,
            landlord_id=landlord_id,
            tenant_id=tenant_id,
        )
        if payment is None:
            return None
        return await self.credit_repository.list_for_payment_transaction(
            payment_transaction_id=str(payment_id),
            landlord_id=str(landlord_id),
        )

    async def _get_payment(
        self,
        *,
        payment_id: UUID,
        landlord_id: UUID,
        tenant_id: UUID | None,
    ) -> PaymentTransaction | None:
        if tenant_id is not None:
            return await self.payment_repository.get_by_id_for_tenant(
                payment_id=str(payment_id),
                tenant_id=str(tenant_id),
                landlord_id=str(landlord_id),
            )
        return await self.payment_repository.get_by_id_for_landlord(
            payment_id=str(payment_id),
            landlord_id=str(landlord_id),
        )
