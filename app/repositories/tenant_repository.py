from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.unit import Unit


class TenantRepository:
    """
    Database access for tenant records.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_landlord(self, landlord_id: UUID) -> list[Tenant]:
        result = await self.db.execute(
            select(Tenant)
            .where(Tenant.landlord_id == landlord_id)
            .order_by(Tenant.created_at.asc(), Tenant.id.asc())
        )
        return list(result.scalars().all())

    async def get_by_id_and_landlord(
        self, tenant_id: UUID, landlord_id: UUID
    ) -> Tenant | None:
        result = await self.db.execute(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.landlord_id == landlord_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_scope_by_id_and_landlord(
        self,
        *,
        tenant_id: UUID,
        landlord_id: UUID,
    ) -> dict | None:
        result = await self.db.execute(
            select(Tenant.id, Tenant.landlord_id, Tenant.unit_id)
            .where(
                Tenant.id == tenant_id,
                Tenant.landlord_id == landlord_id,
                Tenant.is_active.is_(True),
            )
            .with_for_update()
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def lock_by_id(self, *, tenant_id: UUID) -> bool:
        """Acquire a tenant financial mutex before payment/invoice rows.

        PostgreSQL's FOR NO KEY UPDATE still serializes allocation/invoice
        writers, but remains compatible with the KEY SHARE locks acquired by
        foreign-key checks when concurrent payment rows are inserted for this
        tenant. A stronger FOR UPDATE lock can deadlock when both transactions
        upgrade those foreign-key locks at the same time.
        """
        result = await self.db.execute(
            select(Tenant.id)
            .where(Tenant.id == tenant_id)
            .with_for_update(key_share=True)
        )
        return result.scalar_one_or_none() is not None

    async def create_for_unit(
        self,
        *,
        landlord_id: UUID,
        unit_id: UUID,
        values: dict[str, object],
    ) -> Tenant | None:
        result = await self.db.execute(
            select(Unit)
            .where(Unit.id == unit_id, Unit.landlord_id == landlord_id)
        )
        unit = result.scalar_one_or_none()
        if unit is None:
            return None

        tenant = Tenant(
            landlord_id=landlord_id,
            unit_id=unit_id,
            **values,
        )
        self.db.add(tenant)
        await self.db.flush()
        await self.db.refresh(tenant)
        await self.db.commit()
        return tenant

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
