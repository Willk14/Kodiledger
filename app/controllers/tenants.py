from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.tenant_repository import TenantRepository
from app.schemas.tenant import TenantCreate, TenantRead
from app.security.authorization import (
    require_landlord_context,
    require_role_and_permission,
    require_roles_and_permission,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.tenant_service import TenantService


router = APIRouter(prefix="/tenants", tags=["Tenants"])
TenantReader = Annotated[
    Principal,
    Depends(
        require_roles_and_permission(
            Permission.TENANT_READ,
            Role.LANDLORD,
            Role.CARETAKER,
        )
    ),
]
TenantSelfReader = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.TENANT, Permission.TENANT_READ)),
]
TenantWriter = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.TENANT_WRITE)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


def _service(db: AsyncSession) -> TenantService:
    return TenantService(TenantRepository(db))


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Tenant or unit not found.")


@router.get(
    "",
    response_model=list[TenantRead],
    summary="List tenants in the current landlord scope",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Tenant read access is required."}, 500: {"description": "Internal server error."}, 503: {"description": "Database unavailable."}},
)
async def list_tenants(
    principal: TenantReader,
    db: RlsSession,
) -> list[TenantRead]:
    landlord_id = UUID(require_landlord_context(principal))
    tenants = await _service(db).list_for_landlord(landlord_id)
    return [TenantRead.model_validate(tenant) for tenant in tenants]


@router.get(
    "/me",
    response_model=TenantRead,
    summary="Get the authenticated tenant record",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Tenant self-read access is required."}, 404: {"description": "Tenant record not found."}, 500: {"description": "Internal server error."}, 503: {"description": "Database unavailable."}},
)
async def get_my_tenant(
    principal: TenantSelfReader,
    db: RlsSession,
) -> TenantRead:
    tenant = await _service(db).get_for_self(
        principal.tenant_id,
        principal.landlord_id,
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant record not found.")
    return TenantRead.model_validate(tenant)


@router.get(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Get a tenant in the current landlord scope",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Tenant read access is required."}, 404: {"description": "Tenant not found in this landlord scope."}, 500: {"description": "Internal server error."}, 503: {"description": "Database unavailable."}},
)
async def get_tenant(
    tenant_id: UUID,
    principal: TenantReader,
    db: RlsSession,
) -> TenantRead:
    tenant = await _service(db).get_for_landlord(
        tenant_id,
        UUID(require_landlord_context(principal)),
    )
    if tenant is None:
        raise _not_found()
    return TenantRead.model_validate(tenant)


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant in the current landlord scope",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Landlord tenant write access is required."}, 404: {"description": "Unit not found in this landlord scope."}, 500: {"description": "Internal server error."}, 503: {"description": "Database unavailable."}},
)
async def create_tenant(
    request: TenantCreate,
    principal: TenantWriter,
    db: RlsSession,
) -> TenantRead:
    tenant = await _service(db).create(
        landlord_id=UUID(require_landlord_context(principal)),
        values=request.model_dump(),
    )
    if tenant is None:
        raise _not_found()
    return TenantRead.model_validate(tenant)
