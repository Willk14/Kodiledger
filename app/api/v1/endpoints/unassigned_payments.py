from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.unassigned_payment import (
    UnassignedPaymentRead,
    UnassignedPaymentResolutionRead,
    UnassignedPaymentResolve,
)
from app.security.authorization import (
    require_landlord_context,
    require_role_and_permission,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role
from app.security.rls import get_rls_db
from app.services.unassigned_payment_resolution_service import (
    ResolutionConflict,
    UnassignedPaymentNotFound,
    UnassignedPaymentResolutionService,
)


router = APIRouter(prefix="/unassigned-payments", tags=["Payments"])
PaymentAssigner = Annotated[
    Principal,
    Depends(require_role_and_permission(Role.LANDLORD, Permission.PAYMENT_ASSIGN)),
]
RlsSession = Annotated[AsyncSession, Depends(get_rls_db)]


@router.get(
    "",
    response_model=list[UnassignedPaymentRead],
    summary="List unresolved payments in the current landlord scope",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Landlord payment assignment access is required."}},
)
async def list_unassigned_payments(
    principal: PaymentAssigner,
    db: RlsSession,
) -> list[UnassignedPaymentRead]:
    rows = await UnassignedPaymentResolutionService(db).list_unresolved(
        landlord_id=UUID(require_landlord_context(principal)),
    )
    return [UnassignedPaymentRead.model_validate(row) for row in rows]


@router.post(
    "/{payment_id}/resolve",
    response_model=UnassignedPaymentResolutionRead,
    summary="Assign and financially reconcile an unresolved payment",
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Landlord payment assignment access is required."},
        404: {"description": "Payment or active tenant not found in this landlord scope."},
        409: {"description": "Payment has already been resolved or conflicts with financial records."},
    },
)
async def resolve_unassigned_payment(
    payment_id: UUID,
    request: UnassignedPaymentResolve,
    principal: PaymentAssigner,
    db: RlsSession,
) -> UnassignedPaymentResolutionRead:
    try:
        result = await UnassignedPaymentResolutionService(db).resolve(
            payment_id=payment_id,
            landlord_id=UUID(require_landlord_context(principal)),
            tenant_id=request.tenant_id,
            resolved_by_user_id=UUID(principal.user_id),
        )
        await db.commit()
    except UnassignedPaymentNotFound as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment or active tenant not found in this landlord scope.",
        ) from exc
    except ResolutionConflict as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception:
        await db.rollback()
        raise
    return UnassignedPaymentResolutionRead.model_validate(result)
