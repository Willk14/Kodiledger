from unittest.mock import AsyncMock

import pytest

from app.schemas.mpesa import MpesaStkPushCallbackPayload
from app.repositories.stk_push_request_repository import StkPushRequestRepository
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
async def test_reconciliation_failure_rolls_back_and_releases_redis_lock(monkeypatch):
    service, reconciliation_service, idempotency_service = failed_service()

    monkeypatch.setattr(
        StkPushRequestRepository,
        "mark_callback_received",
        AsyncMock(return_value=(True, None)),
    )

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

    assert db.commit.await_count == 2
    webhook_repository.schedule_retry.assert_awaited_once_with(
        "raw-webhook-id",
        "forced reconciliation failure",
        delay_seconds=30,
    )



def success_payload() -> MpesaStkPushCallbackPayload:
    return MpesaStkPushCallbackPayload(
        Body={
            "stkCallback": {
                "MerchantRequestID": "TEST-MERCHANT",
                "CheckoutRequestID": "TEST-CHECKOUT",
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 1},
                        {"Name": "MpesaReceiptNumber", "Value": "TEST-RECEIPT-002"},
                        {"Name": "PhoneNumber", "Value": "254700000001"},
                    ]
                },
            }
        }
    )


@pytest.mark.asyncio
async def test_error_before_inbox_commit_still_saves_callback_for_retry(monkeypatch):
    service, reconciliation_service, _ = failed_service()
    monkeypatch.setattr(
        StkPushRequestRepository,
        "mark_callback_received",
        AsyncMock(side_effect=RuntimeError("forced schema failure")),
    )
    db = AsyncMock()
    service.webhook_repository.create_raw_webhook.return_value = "saved-id"

    result = await service.process_mpesa_callback(payload=success_payload(), db=db)

    assert result["ResultCode"] == 1
    service.webhook_repository.create_raw_webhook.assert_awaited_once()
    service.webhook_repository.schedule_retry.assert_awaited_once_with(
        "saved-id", "forced schema failure", delay_seconds=30
    )
    db.commit.assert_awaited_once()
    reconciliation_service.reconcile_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_invoice_callback_uses_invoice_landlord_not_shortcode(monkeypatch):
    service, reconciliation_service, idempotency_service = failed_service()
    monkeypatch.setattr(
        StkPushRequestRepository,
        "mark_callback_received",
        AsyncMock(return_value=(True, "invoice-id")),
    )
    service.webhook_repository.create_raw_webhook.return_value = "raw-id"
    service.landlord_repository.get_by_invoice_id.return_value = "invoice-landlord"
    idempotency_service.acquire.return_value = (True, "token")
    service.payment_processing_repository.claim_payment.return_value = True
    reconciliation_service.reconcile_payment.return_value = {"status": "MATCHED"}

    result = await service.process_mpesa_callback(payload=success_payload(), db=AsyncMock())

    assert result["ResultCode"] == 0
    service.landlord_repository.get_by_invoice_id.assert_awaited_once_with("invoice-id")
    service.landlord_repository.get_by_business_shortcode.assert_not_awaited()
    assert reconciliation_service.reconcile_payment.await_args.kwargs["landlord_id"] == "invoice-landlord"


@pytest.mark.asyncio
async def test_replay_rejects_merchant_mismatch_and_counts_attempt(monkeypatch):
    service, reconciliation_service, _ = failed_service()
    monkeypatch.setattr(
        StkPushRequestRepository,
        "get_by_checkout_id",
        AsyncMock(return_value={"merchant_request_id": "OTHER", "invoice_id": None}),
    )
    db = AsyncMock()

    result = await service.process_mpesa_callback(
        payload=success_payload(), db=db, raw_webhook_id="raw-id", persist_inbox=False
    )

    assert result["ResultCode"] == 1
    service.webhook_repository.schedule_retry.assert_awaited_once()
    service.webhook_repository.create_raw_webhook.assert_not_awaited()
    reconciliation_service.reconcile_payment.assert_not_awaited()
