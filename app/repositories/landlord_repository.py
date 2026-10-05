from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.property import Property


class LandlordRepository:
    """
    Database access for landlord records.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count_properties_for_landlord(self, landlord_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(Property.id)).where(
                Property.landlord_id == landlord_id,
            )
        )
        return int(result.scalar_one())

    async def get_by_business_shortcode(
        self,
        shortcode: str,
    ) -> str | None:
        """
        Return the landlord UUID associated with an M-Pesa shortcode.
        """

        result = await self.db.execute(
            text(
                """
                SELECT id
                FROM landlords
                WHERE business_shortcode = :shortcode
                LIMIT 1
                """
            ),
            {
                "shortcode": str(shortcode),
            },
        )

        landlord = result.mappings().first()

        if not landlord:
            return None

        return str(landlord["id"])
