from __future__ import annotations

from uuid import UUID

from app.models.property import Property
from app.repositories.property_repository import PropertyRepository


class PropertyQueryService:
    """Application operations for landlord-scoped property reads."""

    def __init__(self, repository: PropertyRepository) -> None:
        self.repository = repository

    async def list_for_landlord(self, landlord_id: str) -> list[Property]:
        return await self.repository.list_by_landlord(UUID(landlord_id))

    async def get_for_landlord(
        self,
        property_id: UUID,
        landlord_id: str,
    ) -> Property | None:
        return await self.repository.get_by_id_and_landlord(
            property_id,
            UUID(landlord_id),
        )
