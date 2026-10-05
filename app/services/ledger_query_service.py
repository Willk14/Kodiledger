from __future__ import annotations

from uuid import UUID

from app.models.ledger_entry import LedgerEntry
from app.repositories.ledger_repository import LedgerRepository


class LedgerQueryService:
    """Read-only landlord-scoped ledger queries."""

    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    async def list_for_landlord(self, landlord_id: UUID) -> list[LedgerEntry]:
        return await self.repository.list_by_landlord(str(landlord_id))

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
