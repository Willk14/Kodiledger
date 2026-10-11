from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.property_repository import PropertyRepository
from app.schemas.property import PropertyRead
from app.security.authorization import (
    require_landlord_context,
    require_role_and_permission,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.property_query_service import PropertyQueryService


router = APIRouter(prefix="/properties", tags=["Properties"])
PROPERTY_READ_ERRORS = {
    401: {"description": "Authentication required or token is invalid."},
    403: {"description": "Landlord role or property-read permission is required."},
    500: {"description": "Unexpected database or server failure."},
    503: {"description": "Authentication dependencies are unavailable."},
}

PropertyReader = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.PROPERTY_READ)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


def _service(db: AsyncSession) -> PropertyQueryService:
    return PropertyQueryService(PropertyRepository(db))


@router.get(
    "",
    response_model=list[PropertyRead],
    summary="List landlord properties",
    responses=PROPERTY_READ_ERRORS,
)
async def list_properties(
    principal: PropertyReader,
    db: RlsSession,
) -> list[PropertyRead]:
    landlord_id = require_landlord_context(principal)
    properties = await _service(db).list_for_landlord(landlord_id)
    return [PropertyRead.model_validate(item) for item in properties]


@router.get(
    "/{property_id}",
    response_model=PropertyRead,
    summary="Get a landlord property",
    responses={
        **PROPERTY_READ_ERRORS,
        404: {"description": "Property not found in this landlord scope."},
    },
)
async def get_property(
    property_id: UUID,
    principal: PropertyReader,
    db: RlsSession,
) -> PropertyRead:
    landlord_id = require_landlord_context(principal)
    property_record = await _service(db).get_for_landlord(property_id, landlord_id)
    if property_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found.",
        )
    return PropertyRead.model_validate(property_record)
