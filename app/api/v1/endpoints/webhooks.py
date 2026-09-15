from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_system_db
from app.core.dependencies import get_webhook_service
from app.schemas.mpesa import MpesaStkPushCallbackPayload
from app.services.webhook_service import WebhookService


router = APIRouter()


@router.post(
    "/mpesa",
    status_code=status.HTTP_200_OK,
)
async def receive_mpesa_webhook(
    payload: MpesaStkPushCallbackPayload,
    db: AsyncSession = Depends(get_system_db),
    service: WebhookService = Depends(get_webhook_service),
):
    """
    Receive an M-Pesa STK callback.

    The endpoint is responsible only for HTTP transport
    and dependency injection.
    """

    return await service.process_mpesa_callback(
        payload=payload,
        db=db,
    )
    
