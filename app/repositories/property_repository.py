from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.property import Property


class PropertyRepository:
    """Read and create landlord-scoped property records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, landlord_id: UUID, values: dict[str, object]) -> Property:
        property_record = Property(landlord_id=landlord_id, **values)
        self.db.add(property_record)
        await self.db.flush()
        await self.db.refresh(property_record)
        await self.db.commit()
        return property_record

    async def list_by_landlord(self, landlord_id: UUID) -> list[Property]:
        statement = (
            select(Property)
            .where(Property.landlord_id == landlord_id)
            .order_by(Property.created_at.asc(), Property.id.asc())
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def get_by_id_and_landlord(
        self,
        property_id: UUID,
        landlord_id: UUID,
    ) -> Property | None:
        statement = select(Property).where(
            Property.id == property_id,
            Property.landlord_id == landlord_id,
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()
