from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security.authorization import require_role_and_permission
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role


router = APIRouter(
    prefix="/bff/landlord",
    tags=["Landlord"],
)


@router.get("/me")
async def get_landlord_context(
    principal: Principal = Depends(
        require_role_and_permission(
            Role.LANDLORD,
            Permission.PROPERTY_READ,
        )
    ),
) -> dict[str, str]:
    """
    Return the authenticated landlord context.

    This endpoint establishes the landlord API boundary
    and verifies that the authenticated principal is both
    a landlord and has property-read permission.
    """
    return {
        "user_id": principal.user_id,
        "role": principal.role.value,
        "landlord_id": principal.landlord_id or "",
    }