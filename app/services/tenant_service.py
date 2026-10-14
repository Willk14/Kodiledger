from __future__ import annotations

from uuid import UUID

from app.models.tenant import Tenant
from app.repositories.tenant_repository import TenantRepository


class TenantService:
    def __init__(self, repository: TenantRepository) -> None:
        self.repository = repository

    async def list_for_landlord(self, landlord_id: UUID) -> list[Tenant]:
        return await self.repository.list_by_landlord(landlord_id)

    async def get_for_landlord(
        self, tenant_id: UUID, landlord_id: UUID
    ) -> Tenant | None:
        return await self.repository.get_by_id_and_landlord(
            tenant_id,
            landlord_id,
        )

    async def get_for_self(
        self, tenant_id: str | None, landlord_id: str | None
    ) -> Tenant | None:
        if tenant_id is None or landlord_id is None:
            return None
        return await self.repository.get_by_id_and_landlord(
            UUID(tenant_id),
            UUID(landlord_id),
        )

    async def create(
        self,
        *,
        landlord_id: UUID,
        values: dict[str, object],
    ) -> Tenant | None:
        tenant_values = dict(values)
        unit_id = UUID(str(tenant_values.pop("unit_id")))
        return await self.repository.create_for_unit(
            landlord_id=landlord_id,
            unit_id=unit_id,
            values=tenant_values,
        )
