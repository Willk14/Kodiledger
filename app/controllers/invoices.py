from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.invoice_repository import (
    DuplicateInvoiceNumberError,
    InvoiceRepository,
)
from app.schemas.invoice import InvoiceCreate, InvoiceRead
from app.security.authorization import (
    require_landlord_context,
    require_role_and_permission,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.invoice_service import InvoiceService


router = APIRouter(prefix="/invoices", tags=["Invoices"])
InvoiceReader = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.INVOICE_READ)),
]
InvoiceWriter = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.INVOICE_WRITE)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


def _service(db: AsyncSession) -> InvoiceService:
    return InvoiceService(InvoiceRepository(db))


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Invoice, unit, or tenant not found in this landlord scope.",
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="An invoice with this invoice number already exists.",
    )


@router.get(
    "",
    response_model=list[InvoiceRead],
    summary="List invoices in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord invoice read access is required."},
        500: {"description": "Internal server error."},
        503: {"description": "Database unavailable."},
    },
)
async def list_invoices(
    principal: InvoiceReader,
    db: RlsSession,
) -> list[InvoiceRead]:
    landlord_id = UUID(require_landlord_context(principal))
    invoices = await _service(db).list_for_landlord(landlord_id)
    return [InvoiceRead.model_validate(invoice) for invoice in invoices]


@router.get(
    "/{invoice_id}",
    response_model=InvoiceRead,
    summary="Get an invoice in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord invoice read access is required."},
        404: {"description": "Invoice not found in this landlord scope."},
        500: {"description": "Internal server error."},
        503: {"description": "Database unavailable."},
    },
)
async def get_invoice(
    invoice_id: UUID,
    principal: InvoiceReader,
    db: RlsSession,
) -> InvoiceRead:
    invoice = await _service(db).get_for_landlord(
        invoice_id,
        UUID(require_landlord_context(principal)),
    )
    if invoice is None:
        raise _not_found()
    return InvoiceRead.model_validate(invoice)


@router.post(
    "",
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invoice for a tenant in the current landlord scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord invoice write access is required."},
        404: {"description": "Unit or tenant is not in this landlord scope."},
        409: {"description": "Invoice number already exists."},
        500: {"description": "Internal server error."},
        503: {"description": "Database unavailable."},
    },
)
async def create_invoice(
    request: InvoiceCreate,
    principal: InvoiceWriter,
    db: RlsSession,
) -> InvoiceRead:
    try:
        invoice = await _service(db).create(
            landlord_id=UUID(require_landlord_context(principal)),
            values=request.model_dump(),
        )
    except DuplicateInvoiceNumberError as exc:
        await db.rollback()
        raise _conflict() from exc
    except Exception:
        await db.rollback()
        raise
    if invoice is None:
        await db.rollback()
        raise _not_found()
    await db.commit()
    return InvoiceRead.model_validate(invoice)
