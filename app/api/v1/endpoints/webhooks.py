from fastapi import APIRouter, Depends, HTTPException, Request, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_system_db
from app.core.dependencies import get_webhook_service
from app.schemas.mpesa import MpesaStkPushCallbackPayload
from app.security.mpesa_callback import (
    enforce_mpesa_callback_source,
    enforce_mpesa_callback_token,
)
from app.services.webhook_service import UnmatchedStkCallback, WebhookService


router = APIRouter()


@router.post(
    "/mpesa",
    status_code=status.HTTP_200_OK,
)
async def receive_mpesa_webhook(
    payload: MpesaStkPushCallbackPayload,
    request: Request,
    db: AsyncSession = Depends(get_system_db),
    service: WebhookService = Depends(get_webhook_service),
):
    """
    Receive an M-Pesa STK callback.

    The endpoint is responsible only for HTTP transport
    and dependency injection.
    """
    enforce_mpesa_callback_token(request)
    enforce_mpesa_callback_source(request)
    try:
        return await service.process_mpesa_callback(
            payload=payload,
            db=db,
        )
    except UnmatchedStkCallback as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Callback does not match an initiated STK request.",
        ) from exc
