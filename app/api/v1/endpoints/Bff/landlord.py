from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.authorization import require_role_and_permission
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db


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
    db: AsyncSession = Depends(get_rls_db),
) -> dict[str, str | int]:
    """
    Return the authenticated landlord context.

    The database query intentionally does not contain a landlord_id
    filter. PostgreSQL RLS is responsible for limiting the result
    to the authenticated landlord's rows.
    """

    result = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM properties
        """)
    )

    property_count = int(result.scalar_one())

    return {
        "user_id": principal.user_id,
        "role": principal.role.value,
        "landlord_id": principal.landlord_id or "",
        "property_count": property_count,
    }