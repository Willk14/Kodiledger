from __future__ import annotations

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.security.dependencies import get_current_principal
from app.security.principals import Principal


async def set_rls_context(
    db: AsyncSession,
    principal: Principal,
) -> None:
    """
    Set the PostgreSQL transaction-local security context.

    The settings are local to the current transaction.
    """

    landlord_id = principal.landlord_id or ""
    user_id = principal.user_id
    role = principal.role.value

    await db.execute(
        text(
            """
            SELECT
                set_config(
                    'app.current_landlord_id',
                    :landlord_id,
                    true
                ),
                set_config(
                    'app.current_user_id',
                    :user_id,
                    true
                ),
                set_config(
                    'app.current_role',
                    :role,
                    true
                )
            """
        ),
        {
            "landlord_id": landlord_id,
            "user_id": user_id,
            "role": role,
        },
    )


async def get_rls_db(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> AsyncSession:
    """
    Return a database session with the authenticated
    principal's PostgreSQL RLS context established.
    """

    await set_rls_context(
        db=db,
        principal=principal,
    )

    return db
