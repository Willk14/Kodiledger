from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TenantRepository:
    """
    Database access for tenant records.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_by_phone(
        self,
        phone: str,
        landlord_id: str,
    ) -> dict | None:
        """
        Find an active tenant belonging to the specified landlord.

        Returns:
            A dictionary containing tenant id, landlord_id, and unit_id,
            or None when no matching active tenant exists.
        """

        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    unit_id
                FROM tenants
                WHERE primary_phone = :phone
                  AND landlord_id = :landlord_id
                  AND is_active = TRUE
                LIMIT 1
                """
            ),
            {
                "phone": phone,
                "landlord_id": landlord_id,
            },
        )

        tenant = result.mappings().first()

        if not tenant:
            return None

        return dict(tenant)
    