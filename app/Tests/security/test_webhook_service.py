from unittest.mock import AsyncMock

import pytest

from app.schemas.mpesa import MpesaStkPushCallbackPayload
from app.services.webhook_service import WebhookService


def failed_service() -> tuple[WebhookService, AsyncMock, AsyncMock]:
    webhook_repository = AsyncMock()
    landlord_repository = AsyncMock()
    payment_processing_repository = AsyncMock()
    idempotency_service = AsyncMock()
    reconciliation_service = AsyncMock()

    service = WebhookService(
        webhook_repository=webhook_repository,
        landlord_repository=landlord_repository,
        payment_processing_repository=payment_processing_repository,
        idempotency_service=idempotency_service,
        reconciliation_service=reconciliation_service,
    )

    return service, reconciliation_service, idempotency_service


@pytest.mark.asyncio
async def test_reconciliation_failure_rolls_back_and_releases_redis_lock():
    service, reconciliation_service, idempotency_service = failed_service()

    db = AsyncMock()

    webhook_repository = service.webhook_repository
    landlord_repository = service.landlord_repository
    payment_processing_repository = service.payment_processing_repository

    webhook_repository.create_raw_webhook.return_value = "raw-webhook-id"

    landlord_repository.get_by_business_shortcode.return_value = "landlord-id"

    idempotency_service.acquire.return_value = (
        True,
        "redis-lock-token",
    )

    payment_processing_repository.claim_payment.return_value = True

    reconciliation_service.reconcile_payment.side_effect = RuntimeError(
        "forced reconciliation failure"
    )

    payload = MpesaStkPushCallbackPayload(
        Body={
            "stkCallback": {
                "MerchantRequestID": "TEST-MERCHANT",
                "CheckoutRequestID": "TEST-CHECKOUT",
                "ResultCode": 0,
                "ResultDesc": (
                    "The service request is processed successfully."
                ),
                "CallbackMetadata": {
                    "Item": [
                        {
                            "Name": "Amount",
                            "Value": 150,
                        },
                        {
                            "Name": "MpesaReceiptNumber",
                            "Value": "TEST-ROLLBACK-001",
                        },
                        {
                            "Name": "PhoneNumber",
                            "Value": "254700000001",
                        },
                    ]
                },
            }
        }
    )

    result = await service.process_mpesa_callback(
        payload=payload,
        db=db,
    )

    assert result["ResultCode"] == 1
    assert "forced reconciliation failure" in result["ResultDesc"]

    db.rollback.assert_awaited_once()

    idempotency_service.release.assert_awaited_once_with(
        receipt="TEST-ROLLBACK-001",
        token="redis-lock-token",
    )

    webhook_repository.create_raw_webhook.assert_awaited_once()

    payment_processing_repository.claim_payment.assert_awaited_once()

    reconciliation_service.reconcile_payment.assert_awaited_once()

    db.commit.assert_not_awaited()

    