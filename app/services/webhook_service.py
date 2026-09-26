from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.config import settings

from app.repositories.landlord_repository import LandlordRepository
from app.repositories.payment_processing_repository import (
    PaymentProcessingRepository,
)
from app.repositories.webhook_repository import WebhookRepository

from app.services.idempotency_service import IdempotencyService
from app.services.reconciliation_service import ReconciliationService


class WebhookService:
    """
    Application service responsible for orchestrating M-Pesa
    webhook processing.

    Responsibilities:
        - Parse the callback
        - Persist the raw webhook
        - Handle failed callbacks
        - Validate successful callbacks
        - Resolve landlord
        - Acquire Redis fast-path lock
        - Claim payment in PostgreSQL
        - Reconcile the payment
        - Update processing state
        - Commit or rollback the transaction

    It does NOT:
        - Execute SQL directly
        - Manage Redis directly
        - Implement ledger persistence
        - Implement tenant persistence
        - Know HTTP response mechanics
    """

    def __init__(
        self,
        webhook_repository: WebhookRepository,
        landlord_repository: LandlordRepository,
        payment_processing_repository: PaymentProcessingRepository,
        idempotency_service: IdempotencyService,
        reconciliation_service: ReconciliationService,
    ) -> None:
        self.webhook_repository = webhook_repository
        self.landlord_repository = landlord_repository
        self.payment_processing_repository = payment_processing_repository
        self.idempotency_service = idempotency_service
        self.reconciliation_service = reconciliation_service

    async def process_mpesa_callback(
        self,
        payload: Any,
        db,
    ) -> dict[str, Any]:
        """
        Process an M-Pesa STK callback.

        Returns a transport-neutral result that the API layer
        can convert into an HTTP response.
        """

        redis_receipt: str | None = None
        redis_token: str | None = None

        try:
            # ====================================================
            # TEMPORARY DATABASE IDENTITY DIAGNOSTIC
            # ====================================================

            # ====================================================
            # 1. Extract callback data
            # ====================================================

            stk_data = payload.Body.stkCallback

            merchant_request_id = stk_data.MerchantRequestID
            checkout_request_id = stk_data.CheckoutRequestID
            result_code = stk_data.ResultCode
            result_desc = stk_data.ResultDesc

            receipt, amount, phone = self._extract_payment_metadata(
                stk_data
            )

            # ====================================================
            # 2. Persist the raw webhook
            # ====================================================

            raw_payload = payload.model_dump(
                mode="json"
            )

            raw_webhook_id = (
                await self.webhook_repository.create_raw_webhook(
                    merchant_request_id=merchant_request_id,
                    checkout_request_id=checkout_request_id,
                    receipt=receipt,
                    raw_payload=raw_payload,
                )
            )

            # ====================================================
            # 3. Handle failed M-Pesa transaction
            # ====================================================

            if result_code != 0:
                await db.commit()

                return {
                    "ResultCode": 0,
                    "ResultDesc": "Webhook received successfully",
                    "mpesa_result_code": result_code,
                    "mpesa_result_desc": result_desc,
                    "raw_webhook_id": raw_webhook_id,
                }

            # ====================================================
            # 4. Validate successful payment data
            # ====================================================

            if not receipt:
                raise ValueError(
                    "Successful callback is missing "
                    "M-Pesa receipt"
                )

            if amount <= 0:
                raise ValueError(
                    "Successful callback contains "
                    "invalid amount"
                )

            if not phone:
                raise ValueError(
                    "Successful callback is missing "
                    "phone number"
                )

            # ====================================================
            # 5. Resolve landlord
            # ====================================================

            landlord_id = (
                await self.landlord_repository
                .get_by_business_shortcode(
                    str(settings.MPESA_SHORTCODE)
                )
            )

            if not landlord_id:
                raise ValueError(
                    f"No landlord found for M-Pesa shortcode "
                    f"{settings.MPESA_SHORTCODE}"
                )

            # ====================================================
            # 6. Redis fast-path idempotency
            # ====================================================

            redis_receipt = receipt

            lock_acquired, redis_token = (
                await self.idempotency_service.acquire(
                    receipt
                )
            )

            if not lock_acquired:
                # Redis believes this payment may already
                # be processing.
                #
                # PostgreSQL remains authoritative.

                already_exists = (
                    await self.payment_processing_repository
                    .exists(receipt)
                )

                if already_exists:
                    await db.commit()

                    return {
                        "ResultCode": 0,
                        "ResultDesc": "Duplicate webhook ignored",
                    }

                # Redis lock is stale, but PostgreSQL has
                # never processed this payment.

                lock_acquired = True

            # ====================================================
            # 7. PostgreSQL authoritative idempotency claim
            # ====================================================

            claimed = (
                await self.payment_processing_repository
                .claim_payment(
                    receipt=receipt,
                    raw_webhook_id=raw_webhook_id,
                    landlord_id=landlord_id,
                )
            )

            if not claimed:
                await db.commit()

                return {
                    "ResultCode": 0,
                    "ResultDesc": "Duplicate webhook ignored",
                }

            # ====================================================
            # 8. Financial reconciliation
            # ====================================================

            reconciliation = (
                await self.reconciliation_service
                .reconcile_payment(
                    mpesa_receipt=receipt,
                    amount=Decimal(str(amount)),
                    phone=phone,
                    landlord_id=landlord_id,
                    raw_webhook_id=raw_webhook_id,
                    merchant_request_id=merchant_request_id,
                    checkout_request_id=checkout_request_id,
                    account_ref=None,
                )
            )

            print(
                "Payment reconciliation:",
                reconciliation,
            )

            # ====================================================
            # 9. Update processing state
            # ====================================================

            processing_status = (
                "COMPLETED"
                if reconciliation["status"] == "MATCHED"
                else "UNASSIGNED"
            )

            await self.payment_processing_repository.mark_processed(
                receipt=receipt,
                status=processing_status,
            )

            # ====================================================
            # 10. Commit atomic transaction
            # ====================================================

            await db.commit()

            # The payment completed successfully.
            # Keep the Redis lock until the TTL expires.

            redis_receipt = None
            redis_token = None

            return {
                "ResultCode": 0,
                "ResultDesc": (
                    "Webhook processed successfully"
                ),
                "reconciliation": reconciliation,
            }

        except Exception as exc:
            # ====================================================
            # 11. Roll back database transaction
            # ====================================================

            await db.rollback()

            # ====================================================
            # 12. Release Redis lock
            # ====================================================

            if redis_receipt and redis_token:
                await self.idempotency_service.release(
                    receipt=redis_receipt,
                    token=redis_token,
                )

            # ====================================================
            # 13. Log error
            # ====================================================

            print("\n" + "=" * 60)
            print("WEBHOOK ERROR")
            print("=" * 60)
            print(f"{type(exc).__name__}: {exc}")
            print("=" * 60 + "\n")

            return {
                "ResultCode": 1,
                "ResultDesc": (
                    f"Internal error recorded: {str(exc)}"
                ),
            }

    @staticmethod
    def _extract_payment_metadata(
        stk_data,
    ) -> tuple[str | None, Decimal, str | None]:
        """
        Extract payment metadata from a successful STK callback.

        Returns:
            (receipt, amount, phone)
        """

        receipt: str | None = None
        amount = Decimal("0")
        phone: str | None = None

        if (
            stk_data.ResultCode != 0
            or not stk_data.CallbackMetadata
        ):
            return receipt, amount, phone

        metadata = stk_data.CallbackMetadata

        items = (
            metadata.get("Item", [])
            if isinstance(metadata, dict)
            else getattr(metadata, "Item", [])
        )

        for item in items:
            name = (
                item.get("Name")
                if isinstance(item, dict)
                else getattr(item, "Name", None)
            )

            value = (
                item.get("Value")
                if isinstance(item, dict)
                else getattr(item, "Value", None)
            )

            if name == "MpesaReceiptNumber":
                receipt = (
                    str(value)
                    if value is not None
                    else None
                )

            elif name == "Amount":
                if value is not None:
                    amount = Decimal(str(value))

            elif name == "PhoneNumber":
                phone = (
                    str(value)
                    if value is not None
                    else None
                )

        return receipt, amount, phone

    