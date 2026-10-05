from __future__ import annotations

from uuid import UUID

from app.models.payment_transaction import PaymentTransaction
from app.repositories.payment_transaction_repository import (
    PaymentTransactionRepository,
)


class PaymentQueryService:
    def __init__(self, repository: PaymentTransactionRepository) -> None:
        self.repository = repository

    async def list_for_landlord(
        self,
        landlord_id: UUID,
    ) -> list[PaymentTransaction]:
        return await self.repository.list_by_landlord(str(landlord_id))

    async def list_for_tenant(
        self,
        *,
        tenant_id: UUID,
        landlord_id: UUID,
    ) -> list[PaymentTransaction]:
        return await self.repository.list_by_tenant(
            tenant_id=str(tenant_id),
            landlord_id=str(landlord_id),
        )

    async def get_for_landlord(
        self,
        *,
        payment_id: UUID,
        landlord_id: UUID,
    ) -> PaymentTransaction | None:
        return await self.repository.get_by_id_for_landlord(
            payment_id=str(payment_id),
            landlord_id=str(landlord_id),
        )

    async def get_for_tenant(
        self,
        *,
        payment_id: UUID,
        tenant_id: UUID,
        landlord_id: UUID,
    ) -> PaymentTransaction | None:
        return await self.repository.get_by_id_for_tenant(
            payment_id=str(payment_id),
            tenant_id=str(tenant_id),
            landlord_id=str(landlord_id),
        )
