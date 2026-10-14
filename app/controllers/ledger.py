from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ledger_repository import LedgerRepository
from app.schemas.ledger_entry import LedgerEntryPage, LedgerEntryRead
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
    response_model=LedgerEntryPage,
    summary="List ledger entries in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord payment read access is required."},
        422: {"description": "A query parameter is invalid."},
        500: {"description": "Unexpected ledger query failure."},
    },
)
async def list_ledger_entries(
    principal: LedgerReader,
    db: RlsSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    payment_transaction_id: UUID | None = None,
    tenant_id: UUID | None = None,
    invoice_id: UUID | None = None,
    unit_id: UUID | None = None,
    property_id: UUID | None = None,
    receipt: str | None = Query(default=None, min_length=1, max_length=100),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> LedgerEntryPage:
    for value, parameter in (
        (created_from, "created_from"),
        (created_to, "created_to"),
    ):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{parameter} must include a timezone offset.",
            )
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="created_from must be earlier than or equal to created_to.",
        )

    entries, total = await _service(db).list_for_landlord(
        UUID(require_landlord_context(principal)),
        payment_transaction_id=payment_transaction_id,
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        unit_id=unit_id,
        property_id=property_id,
        receipt=receipt,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return LedgerEntryPage(
        items=[LedgerEntryRead.model_validate(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{entry_id}",
    response_model=LedgerEntryRead,
    summary="Get a ledger entry in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord payment read access is required."},
        404: {"description": "Ledger entry not found in this landlord scope."},
        422: {"description": "The ledger entry ID is invalid."},
        500: {"description": "Unexpected ledger query failure."},
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
