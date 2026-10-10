from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.unit_repository import UnitRepository
from app.schemas.unit import UnitCreate, UnitRead, UnitUpdate
from app.security.authorization import (
    require_landlord_context,
    require_role_and_permission,
    require_roles_and_permission,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.unit_service import UnitConflictError, UnitService


router = APIRouter(tags=["Units"])
UnitReader = Annotated[
    Principal,
    Depends(
        require_roles_and_permission(
            Permission.UNIT_READ,
            Role.LANDLORD,
            Role.CARETAKER,
        )
    ),
]
UnitWriter = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.UNIT_WRITE)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


def _service(db: AsyncSession) -> UnitService:
    return UnitService(UnitRepository(db), db)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Unit or property not found.")


def _conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="A unit with this number already exists in the property.")


@router.get(
    "/properties/{property_id}/units",
    response_model=list[UnitRead],
    summary="List units in a property",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Unit read access is required."}, 404: {"description": "Property not found in this landlord scope."}},
)
async def list_property_units(
    property_id: UUID,
    principal: UnitReader,
    db: RlsSession,
) -> list[UnitRead]:
    landlord_id = require_landlord_context(principal)
    units = await _service(db).list_for_property(property_id, UUID(landlord_id))
    if units is None:
        raise _not_found()
    return [UnitRead.model_validate(unit) for unit in units]


@router.post(
    "/properties/{property_id}/units",
    response_model=UnitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a unit in a property",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Landlord unit write access is required."}, 404: {"description": "Property not found in this landlord scope."}, 409: {"description": "Unit number already exists in this property."}},
)
async def create_property_unit(
    property_id: UUID,
    request: UnitCreate,
    principal: UnitWriter,
    db: RlsSession,
) -> UnitRead:
    landlord_id = UUID(require_landlord_context(principal))
    try:
        unit = await _service(db).create(
            property_id=property_id,
            landlord_id=landlord_id,
            values=request.model_dump(),
        )
    except UnitConflictError as exc:
        raise _conflict() from exc
    if unit is None:
        raise _not_found()
    return UnitRead.model_validate(unit)


@router.get(
    "/units/{unit_id}",
    response_model=UnitRead,
    summary="Get a unit",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Unit read access is required."}, 404: {"description": "Unit not found in this landlord scope."}},
)
async def get_unit(
    unit_id: UUID,
    principal: UnitReader,
    db: RlsSession,
) -> UnitRead:
    unit = await _service(db).get(unit_id, UUID(require_landlord_context(principal)))
    if unit is None:
        raise _not_found()
    return UnitRead.model_validate(unit)


@router.patch(
    "/units/{unit_id}",
    response_model=UnitRead,
    summary="Update a unit",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Landlord unit write access is required."}, 404: {"description": "Unit not found in this landlord scope."}, 409: {"description": "Unit number already exists in the property."}},
)
async def update_unit(
    unit_id: UUID,
    request: UnitUpdate,
    principal: UnitWriter,
    db: RlsSession,
) -> UnitRead:
    values = request.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=422, detail="At least one unit field must be provided.")
    try:
        unit = await _service(db).update(
            unit_id,
            UUID(require_landlord_context(principal)),
            values,
        )
    except UnitConflictError as exc:
        raise _conflict() from exc
    if unit is None:
        raise _not_found()
    return UnitRead.model_validate(unit)
