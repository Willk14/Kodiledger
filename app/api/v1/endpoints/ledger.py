from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ledger_repository import LedgerRepository
from app.schemas.ledger_entry import LedgerEntryRead
from app.security.authorization import require_landlord_context, require_role_and_permission
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.ledger_query_service import LedgerQueryService


router = APIRouter(prefix="/ledger", tags=["Ledger"])
LedgerReader = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.PAYMENT_READ)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


def _service(db: AsyncSession) -> LedgerQueryService:
    return LedgerQueryService(LedgerRepository(db))


@router.get(
    "",
    response_model=list[LedgerEntryRead],
    summary="List ledger entries in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord payment read access is required."},
    },
)
async def list_ledger_entries(
    principal: LedgerReader,
    db: RlsSession,
) -> list[LedgerEntryRead]:
    entries = await _service(db).list_for_landlord(
        UUID(require_landlord_context(principal))
    )
    return [LedgerEntryRead.model_validate(entry) for entry in entries]


@router.get(
    "/{entry_id}",
    response_model=LedgerEntryRead,
    summary="Get a ledger entry in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord payment read access is required."},
        404: {"description": "Ledger entry not found in this landlord scope."},
    },
)
async def get_ledger_entry(
    entry_id: UUID,
    principal: LedgerReader,
    db: RlsSession,
) -> LedgerEntryRead:
    entry = await _service(db).get_for_landlord(
        entry_id=entry_id,
        landlord_id=UUID(require_landlord_context(principal)),
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ledger entry not found in this landlord scope.",
        )
    return LedgerEntryRead.model_validate(entry)
