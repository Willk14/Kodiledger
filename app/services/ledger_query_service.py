from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models.ledger_entry import LedgerEntry
from app.repositories.ledger_repository import LedgerRepository


class LedgerQueryService:
    """Read-only landlord-scoped ledger queries."""

    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    async def list_for_landlord(
        self,
        landlord_id: UUID,
        *,
        payment_transaction_id: UUID | None,
        tenant_id: UUID | None,
        invoice_id: UUID | None,
        unit_id: UUID | None,
        property_id: UUID | None,
        receipt: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[LedgerEntry], int]:
        entries, total = await self.repository.list_by_landlord(
            str(landlord_id),
            payment_transaction_id=(
                str(payment_transaction_id)
                if payment_transaction_id is not None else None
            ),
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            invoice_id=str(invoice_id) if invoice_id is not None else None,
            unit_id=str(unit_id) if unit_id is not None else None,
            property_id=str(property_id) if property_id is not None else None,
            receipt=receipt,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
        return entries, total

    async def get_for_landlord(
        self,
        *,
        entry_id: UUID,
        landlord_id: UUID,
    ) -> LedgerEntry | None:
        return await self.repository.get_by_id_and_landlord(
            entry_id=str(entry_id),
            landlord_id=str(landlord_id),
        )
