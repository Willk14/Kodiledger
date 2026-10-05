from __future__ import annotations

from uuid import UUID

from app.repositories.landlord_repository import LandlordRepository


class LandlordService:
    """Application operations for the authenticated landlord context."""

    def __init__(self, repository: LandlordRepository) -> None:
        self.repository = repository

    async def count_properties(self, landlord_id: str) -> int:
        return await self.repository.count_properties_for_landlord(
            UUID(landlord_id)
        )
