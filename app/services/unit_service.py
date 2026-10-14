from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.unit import Unit
from app.repositories.unit_repository import UnitRepository


class UnitConflictError(Exception):
    """A unit number conflicts with another unit in the same property."""


class UnitService:
    def __init__(self, repository: UnitRepository, db: AsyncSession) -> None:
        self.repository = repository
        self.db = db

    async def list_for_property(
        self, property_id: UUID, landlord_id: UUID
    ) -> list[Unit] | None:
        if not await self.repository.property_exists(property_id, landlord_id):
            return None
        return await self.repository.list_for_property(property_id, landlord_id)

    async def get(self, unit_id: UUID, landlord_id: UUID) -> Unit | None:
        return await self.repository.get_for_landlord(unit_id, landlord_id)

    async def create(
        self,
        *,
        property_id: UUID,
        landlord_id: UUID,
        values: dict[str, object],
    ) -> Unit | None:
        try:
            return await self.repository.create(
                property_id=property_id,
                landlord_id=landlord_id,
                values=values,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            raise UnitConflictError from exc

    async def update(
        self, unit_id: UUID, landlord_id: UUID, values: dict[str, object]
    ) -> Unit | None:
        unit = await self.repository.get_for_landlord(unit_id, landlord_id)
        if unit is None:
            return None
        try:
            return await self.repository.update(unit, values)
        except IntegrityError as exc:
            await self.db.rollback()
            raise UnitConflictError from exc
