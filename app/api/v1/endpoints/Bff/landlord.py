from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.authorization import (
    require_landlord_context,
    require_role_and_permission,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.repositories.landlord_repository import LandlordRepository
from app.schemas.landlord import LandlordContextRead
from app.services.landlord_service import LandlordService


router = APIRouter(
    prefix="/bff/landlord",
    tags=["Landlord"],
)
LandlordPrincipal = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.PROPERTY_READ)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


@router.get(
    "/me",
    response_model=LandlordContextRead,
    summary="Get the authenticated landlord context",
    responses={
        401: {"description": "Authentication is required or the token is invalid."},
        403: {"description": "An active landlord membership is required."},
        500: {"description": "Unexpected database or server failure."},
        503: {"description": "Authentication dependencies are unavailable."},
    },
)
async def get_landlord_context(
    principal: LandlordPrincipal,
    db: RlsSession,
) -> LandlordContextRead:
    """
    Return the authenticated landlord context.

    The landlord scope comes from the verified membership. The service
    and repository query that scope through the normal RLS-bound session.
    """
    landlord_id = require_landlord_context(principal)
    property_count = await LandlordService(LandlordRepository(db)).count_properties(
        landlord_id
    )
    return LandlordContextRead(
        user_id=principal.user_id,
        role=principal.role,
        landlord_id=landlord_id,
        property_count=property_count,
    )
