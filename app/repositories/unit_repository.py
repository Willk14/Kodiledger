from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.property import Property
from app.models.unit import Unit


class UnitRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def property_exists(self, property_id: UUID, landlord_id: UUID) -> bool:
        result = await self.db.execute(
            select(Property.id).where(
                Property.id == property_id,
                Property.landlord_id == landlord_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_for_property(
        self, property_id: UUID, landlord_id: UUID
    ) -> list[Unit]:
        result = await self.db.execute(
            select(Unit)
            .where(Unit.property_id == property_id, Unit.landlord_id == landlord_id)
            .order_by(Unit.unit_number.asc(), Unit.id.asc())
        )
        return list(result.scalars().all())

    async def get_for_landlord(self, unit_id: UUID, landlord_id: UUID) -> Unit | None:
        result = await self.db.execute(
            select(Unit).where(Unit.id == unit_id, Unit.landlord_id == landlord_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        property_id: UUID,
        landlord_id: UUID,
        values: dict[str, object],
    ) -> Unit | None:
        property_result = await self.db.execute(
            select(Property)
            .where(Property.id == property_id, Property.landlord_id == landlord_id)
            .with_for_update()
        )
        property_record = property_result.scalar_one_or_none()
        if property_record is None:
            return None

        current_count = await self.db.scalar(
            select(func.count(Unit.id)).where(
                Unit.property_id == property_id,
                Unit.landlord_id == landlord_id,
            )
        )
        unit = Unit(property_id=property_id, landlord_id=landlord_id, **values)
        self.db.add(unit)
        property_record.total_units = int(current_count or 0) + 1
        await self.db.flush()
        await self.db.refresh(unit)
        await self.db.commit()
        return unit

    async def update(self, unit: Unit, values: dict[str, object]) -> Unit:
        for name, value in values.items():
            setattr(unit, name, value)
        await self.db.flush()
        await self.db.refresh(unit)
        await self.db.commit()
        return unit
