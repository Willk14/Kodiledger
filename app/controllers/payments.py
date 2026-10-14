from __future__ import annotations

import logging
from typing import Annotated, Any, Mapping
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.configs.database import get_system_db
from app.core.rate_limiter import enforce_stk_push_rate_limit
from app.schemas.mpesa import InvoiceStkPushRequest, StkPushRequest, StkPushResponse
from app.schemas.payment_transaction import PaymentTransactionRead
from app.schemas.payment_financial_detail import (
    PaymentAllocationRead,
    PaymentCreditRead,
)
from app.schemas.stk_status import StkRequestQueueItem, StkRequestQueuePage
from app.repositories.payment_transaction_repository import PaymentTransactionRepository
from app.repositories.payment_allocation_repository import PaymentAllocationRepository
from app.repositories.payment_credit_repository import PaymentCreditRepository
from app.repositories.stk_push_request_repository import StkPushRequestRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.security.authorization import require_landlord_context, require_role_and_permission, require_roles_and_permission
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.payment_initiation_service import payment_initiation_service
from app.services.payment_query_service import PaymentQueryService
from app.services.payment_financial_query_service import PaymentFinancialQueryService


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)
PaymentReader = Annotated[
    Principal,
    Depends(
        require_roles_and_permission(
            Permission.PAYMENT_READ,
            Role.LANDLORD,
            Role.TENANT,
        )
    ),
]
PaymentOperator = Annotated[
    Principal,
    Depends(require_roles_and_permission(Permission.PAYMENT_READ, Role.ADMIN)),
]
InvoicePaymentWriter = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.PAYMENT_CREATE)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


def _query_service(db: AsyncSession) -> PaymentQueryService:
    return PaymentQueryService(PaymentTransactionRepository(db))


def _financial_query_service(db: AsyncSession) -> PaymentFinancialQueryService:
    return PaymentFinancialQueryService(
        PaymentTransactionRepository(db),
        PaymentAllocationRepository(db),
        PaymentCreditRepository(db),
    )


@router.post(
    "/invoices/{invoice_id}/stk-push",
    response_model=StkPushResponse,
    summary="Initiate an STK Push for an outstanding invoice balance",
    responses={404: {"description": "Invoice or active tenant not found in this landlord scope."}, 409: {"description": "Invoice has no amount due."}},
)
async def initiate_invoice_stk_push(
    invoice_id: UUID,
    request: InvoiceStkPushRequest,
    principal: InvoicePaymentWriter,
    db: RlsSession,
    _: None = Depends(enforce_stk_push_rate_limit),
    system_db: AsyncSession = Depends(get_system_db),
) -> StkPushResponse:
    landlord_id = str(UUID(require_landlord_context(principal)))
    invoices = InvoiceRepository(db)
    invoice = await invoices.get_stk_payment_context(
        invoice_id=str(invoice_id), landlord_id=landlord_id
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice or active tenant not found in this landlord scope.")
    if invoice["is_paid"]:
        raise HTTPException(status_code=409, detail="Invoice is already paid.")
    amount_due = invoice["amount_due"]
    if amount_due <= 0:
        raise HTTPException(status_code=409, detail="Invoice has no outstanding balance.")
    if amount_due != int(amount_due):
        raise HTTPException(status_code=409, detail="STK Push requires a whole KES amount; invoice has a fractional balance.")

    await db.commit()
    try:
        response = await payment_initiation_service.initiate_mpesa_stk_push(
            phone_number=request.phone_number,
            amount=int(amount_due),
            account_reference=str(invoice["invoice_number"])[:12],
            transaction_description=f"Rent {invoice['invoice_number']}"[:20],
        )
        if not isinstance(response, Mapping):
            raise RuntimeError("M-Pesa service returned an invalid response.")
        merchant_id = response.get("MerchantRequestID")
        checkout_id = response.get("CheckoutRequestID")
        if not merchant_id or not checkout_id:
            raise RuntimeError("M-Pesa did not return a checkout request ID.")
        await StkPushRequestRepository(system_db).record_initiation(
            str(merchant_id), str(checkout_id), str(invoice_id)
        )
        await system_db.commit()
        return _build_stk_push_response(response)
    except ValueError as exc:
        await system_db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        await system_db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        await system_db.rollback()
        logger.exception("Invoice STK Push initiation failed")
        raise HTTPException(status_code=502, detail="Failed to initiate invoice STK Push.") from exc


def _tenant_scope(principal: Principal) -> UUID | None:
    if principal.role is not Role.TENANT:
        return None
    if principal.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant scope is required.",
        )
    return UUID(principal.tenant_id)


async def _list_for_principal(
    principal: Principal,
    service: PaymentQueryService,
) -> list[PaymentTransactionRead]:
    landlord_id = UUID(require_landlord_context(principal))
    tenant_id = _tenant_scope(principal)
    if tenant_id is not None:
        payments = await service.list_for_tenant(
            tenant_id=tenant_id,
            landlord_id=landlord_id,
        )
    else:
        payments = await service.list_for_landlord(landlord_id)
    return [PaymentTransactionRead.model_validate(payment) for payment in payments]


def _build_stk_push_response(
    response: Mapping[str, Any],
) -> StkPushResponse:
    """
    Convert the M-Pesa service response into the public API response.
    """

    return StkPushResponse(
        MerchantRequestID=str(
            response.get("MerchantRequestID", "")
        ),
        CheckoutRequestID=str(
            response.get("CheckoutRequestID", "")
        ),
        ResponseCode=str(
            response.get("ResponseCode", "")
        ),
        ResponseDescription=str(
            response.get("ResponseDescription", "")
        ),
        CustomerMessage=str(
            response.get("CustomerMessage", "")
        ),
    )


@router.get(
    "",
    response_model=list[PaymentTransactionRead],
    summary="List payment transactions in the authenticated scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Payment read access or membership scope is required."},
        500: {"description": "Internal server error."},
        503: {"description": "Database unavailable."},
    },
)
async def list_payment_transactions(
    principal: PaymentReader,
    db: RlsSession,
) -> list[PaymentTransactionRead]:
    return await _list_for_principal(principal, _query_service(db))


@router.get(
    "/{payment_id}",
    response_model=PaymentTransactionRead,
    summary="Get a payment transaction in the authenticated scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Payment read access or membership scope is required."},
        404: {"description": "Payment transaction not found in this scope."},
        500: {"description": "Internal server error."},
        503: {"description": "Database unavailable."},
    },
)
async def get_payment_transaction(
    payment_id: UUID,
    principal: PaymentReader,
    db: RlsSession,
) -> PaymentTransactionRead:
    landlord_id = UUID(require_landlord_context(principal))
    service = _query_service(db)
    tenant_id = _tenant_scope(principal)
    if tenant_id is not None:
        payment = await service.get_for_tenant(
            payment_id=payment_id,
            tenant_id=tenant_id,
            landlord_id=landlord_id,
        )
    else:
        payment = await service.get_for_landlord(
            payment_id=payment_id,
            landlord_id=landlord_id,
        )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found in this scope.",
        )
    return PaymentTransactionRead.model_validate(payment)


@router.get(
    "/{payment_id}/allocations",
    response_model=list[PaymentAllocationRead],
    summary="List invoice allocations for a payment in the authenticated scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Payment read access or membership scope is required."},
        404: {"description": "Payment transaction not found in this scope."},
        500: {"description": "The payment-allocation query failed."},
        503: {"description": "Authentication or database context is unavailable."},
    },
)
async def list_payment_allocations(
    payment_id: UUID,
    principal: PaymentReader,
    db: RlsSession,
) -> list[PaymentAllocationRead]:
    allocations = await _financial_query_service(db).list_allocations(
        payment_id=payment_id,
        landlord_id=UUID(require_landlord_context(principal)),
        tenant_id=_tenant_scope(principal),
    )
    if allocations is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found in this scope.",
        )
    return [PaymentAllocationRead.model_validate(row) for row in allocations]


@router.get(
    "/{payment_id}/credits",
    response_model=list[PaymentCreditRead],
    summary="List payment credits for a payment in the authenticated scope",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Payment read access or membership scope is required."},
        404: {"description": "Payment transaction not found in this scope."},
        500: {"description": "The payment-credit query failed."},
        503: {"description": "Authentication or database context is unavailable."},
    },
)
async def list_payment_credits(
    payment_id: UUID,
    principal: PaymentReader,
    db: RlsSession,
) -> list[PaymentCreditRead]:
    credits = await _financial_query_service(db).list_credits(
        payment_id=payment_id,
        landlord_id=UUID(require_landlord_context(principal)),
        tenant_id=_tenant_scope(principal),
    )
    if credits is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found in this scope.",
        )
    return [PaymentCreditRead.model_validate(row) for row in credits]


@router.post(
    "/stk-push",
    response_model=StkPushResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate M-Pesa STK Push",
)
async def initiate_stk_push(
    request: StkPushRequest,
    _: None = Depends(enforce_stk_push_rate_limit),
    db: AsyncSession = Depends(get_system_db),
) -> StkPushResponse:
    """
    Initiate an M-Pesa STK Push.

    This endpoint only starts the M-Pesa payment request.

    It does not create a ledger entry.
    Ledger processing happens after the M-Pesa callback
    is received and successfully reconciled.
    """

    try:
        response = await payment_initiation_service.initiate_mpesa_stk_push(
            phone_number=request.phone_number,
            amount=request.amount,
            account_reference="KodiLedger",
            transaction_description="KodiLedger Payment",
        )

        if not isinstance(response, Mapping):
            logger.error(
                "M-Pesa service returned unexpected response type: %s",
                type(response).__name__,
            )

            raise RuntimeError(
                "M-Pesa service returned an invalid response."
            )

        merchant_id = response.get("MerchantRequestID")
        checkout_id = response.get("CheckoutRequestID")
        if merchant_id and checkout_id:
            await StkPushRequestRepository(db).record_initiation(
                str(merchant_id), str(checkout_id)
            )
            await db.commit()

        logger.info(
            "M-Pesa STK Push initiated successfully "
            "(response_code=%s)",
            response.get("ResponseCode"),
        )

        return _build_stk_push_response(response)

    except ValueError as exc:
        logger.warning(
            "Invalid STK Push request: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        logger.error(
            "M-Pesa STK Push upstream/service failure: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception:
        logger.exception(
            "Unexpected STK Push initiation failure"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate M-Pesa STK Push.",
        ) from exc


@router.get(
    "/stk-push/unresolved",
    response_model=StkRequestQueuePage,
    summary="List STK requests awaiting callback reconciliation",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Platform administrator access is required."},
    },
)
async def list_unresolved_stk_requests(
    principal: PaymentOperator,
    db: AsyncSession = Depends(get_system_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> StkRequestQueuePage:
    del principal  # Authorization is enforced by the dependency.
    rows, total = await StkPushRequestRepository(db).list_unresolved(
        limit=limit,
        offset=offset,
    )
    await db.commit()
    items = [
        StkRequestQueueItem(
            id=row["id"],
            checkout_request_id=row["checkout_request_id"],
            status=row["request_status"],
            query_count=row["query_count"],
            created_at=row["created_at"],
            last_queried_at=row["last_queried_at"],
        )
        for row in rows
    ]
    return StkRequestQueuePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/stk-push/{checkout_request_id}/query",
    summary="Query an unresolved STK Push status",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Platform administrator access is required."},
        404: {"description": "STK request not found."},
        409: {"description": "A callback has already been received."},
        502: {"description": "Daraja status query failed."},
    },
)
async def query_stk_push_status(
    checkout_request_id: str,
    principal: PaymentOperator,
    db: AsyncSession = Depends(get_system_db),
) -> dict[str, Any]:
    del principal  # Authorization is enforced by the dependency.
    repository = StkPushRequestRepository(db)
    request_record = await repository.get_by_checkout_id(checkout_request_id)
    if request_record is None:
        raise HTTPException(status_code=404, detail="STK request not found.")
    if request_record["callback_received_at"] is not None:
        raise HTTPException(status_code=409, detail="Callback already received.")

    await db.commit()
    try:
        provider_response = await payment_initiation_service.query_mpesa_stk_push(
            checkout_request_id
        )
    except (RuntimeError, ValueError) as exc:
        await repository.record_query_error(checkout_request_id)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to query M-Pesa status.",
        ) from exc

    query_status = await repository.record_query(
        checkout_request_id, provider_response
    )
    await db.commit()
    return {
        "checkout_request_id": checkout_request_id,
        "status": query_status,
        "provider_response": provider_response,
    }
