import asyncio
import secrets
import traceback
from decimal import Decimal

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.mpesa import MpesaStkPushCallbackPayload
from app.services.payment_service import reconcile_mpesa_payment


router = APIRouter()

IDEMPOTENCY_TTL_SECONDS = 86400


# ============================================================
# Helpers
# ============================================================

def extract_payment_metadata(stk_data):
    """
    Extract successful payment metadata from an M-Pesa STK callback.

    Returns:
        receipt, amount, phone
    """

    receipt: str | None = None
    amount = Decimal("0")
    phone: str | None = None

    # Failed callbacks normally have no CallbackMetadata.
    if stk_data.ResultCode != 0 or not stk_data.CallbackMetadata:
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
            receipt = str(value) if value is not None else None

        elif name == "Amount":
            if value is not None:
                amount = Decimal(str(value))

        elif name == "PhoneNumber":
            phone = str(value) if value is not None else None

    return receipt, amount, phone


async def save_raw_webhook(
    db: AsyncSession,
    merchant_request_id: str,
    checkout_request_id: str,
    receipt: str | None,
    raw_payload: str,
) -> str:
    """
    Store the complete original webhook and return its UUID.
    """

    result = await db.execute(
        text(
            """
            INSERT INTO raw_payment_webhooks (
                source_provider,
                merchant_request_id,
                checkout_request_id,
                mpesa_receipt_number,
                raw_payload,
                processed
            )
            VALUES (
                'SAFARICOM_DARAJA',
                :merchant_request_id,
                :checkout_request_id,
                :receipt,
                CAST(:payload AS JSONB),
                TRUE
            )
            RETURNING id
            """
        ),
        {
            "merchant_request_id": merchant_request_id,
            "checkout_request_id": checkout_request_id,
            "receipt": receipt,
            "payload": raw_payload,
        },
    )

    return str(result.scalar_one())


async def resolve_landlord_id(db: AsyncSession) -> str:
    """
    Resolve landlord using the configured M-Pesa shortcode.
    """

    result = await db.execute(
        text(
            """
            SELECT id
            FROM landlords
            WHERE business_shortcode = :shortcode
            LIMIT 1
            """
        ),
        {
            "shortcode": str(settings.MPESA_SHORTCODE),
        },
    )

    landlord = result.mappings().first()

    if not landlord:
        raise ValueError(
            f"No landlord found for M-Pesa shortcode "
            f"{settings.MPESA_SHORTCODE}"
        )

    return str(landlord["id"])


async def claim_payment(
    db: AsyncSession,
    receipt: str,
    raw_webhook_id: str,
    landlord_id: str,
) -> bool:
    """
    PostgreSQL is the authoritative idempotency mechanism.

    Returns:
        True  -> this request successfully claimed the receipt.
        False -> receipt already exists.
    """

    result = await db.execute(
        text(
            """
            INSERT INTO payment_processing (
                mpesa_receipt_number,
                raw_webhook_id,
                landlord_id,
                status
            )
            VALUES (
                :receipt,
                :raw_webhook_id,
                :landlord_id,
                'PROCESSING'
            )
            ON CONFLICT (mpesa_receipt_number) DO NOTHING
            RETURNING id
            """
        ),
        {
            "receipt": receipt,
            "raw_webhook_id": raw_webhook_id,
            "landlord_id": landlord_id,
        },
    )

    return result.scalar_one_or_none() is not None


async def mark_payment_processed(
    db: AsyncSession,
    receipt: str,
    status_value: str,
) -> None:
    """
    Mark payment processing as complete.
    """

    await db.execute(
        text(
            """
            UPDATE payment_processing
            SET
                status = :status,
                processed_at = NOW()
            WHERE mpesa_receipt_number = :receipt
            """
        ),
        {
            "receipt": receipt,
            "status": status_value,
        },
    )


async def acquire_redis_lock(
    receipt: str,
) -> tuple[bool, str]:
    """
    Redis provides a fast-path lock.

    PostgreSQL remains the authoritative idempotency mechanism.
    """

    token = secrets.token_urlsafe(16)
    redis_client = None

    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            socket_timeout=1.0,
        )

        acquired = await asyncio.wait_for(
            redis_client.set(
                f"mpesa_lock:{receipt}",
                token,
                nx=True,
                ex=IDEMPOTENCY_TTL_SECONDS,
            ),
            timeout=1.0,
        )

        return bool(acquired), token

    except Exception as exc:
        print(
            f"Redis warning: bypassing fast-path lock: {exc}"
        )

        # PostgreSQL still protects idempotency.
        return True, token

    finally:
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass


async def release_redis_lock(
    receipt: str,
    token: str,
) -> None:
    """
    Remove the Redis lock only if it belongs to this request.
    """

    redis_client = None

    script = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    end
    return 0
    """

    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            socket_timeout=1.0,
        )

        await asyncio.wait_for(
            redis_client.eval(
                script,
                1,
                f"mpesa_lock:{receipt}",
                token,
            ),
            timeout=1.0,
        )

    except Exception as exc:
        print(
            f"Redis cleanup warning: {exc}"
        )

    finally:
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass


# ============================================================
# Webhook endpoint
# ============================================================

@router.post(
    "/mpesa",
    status_code=status.HTTP_200_OK,
)
async def receive_mpesa_webhook(
    payload: MpesaStkPushCallbackPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive and process an M-Pesa STK callback.
    """

    redis_receipt: str | None = None
    redis_token: str | None = None

    try:
        # ----------------------------------------------------
        # 1. Extract callback
        # ----------------------------------------------------

        stk_data = payload.Body.stkCallback

        merchant_request_id = stk_data.MerchantRequestID
        checkout_request_id = stk_data.CheckoutRequestID
        result_code = stk_data.ResultCode

        receipt, amount, phone = extract_payment_metadata(
            stk_data
        )

        # ----------------------------------------------------
        # 2. Save raw webhook
        # ----------------------------------------------------

        raw_webhook_id = await save_raw_webhook(
            db=db,
            merchant_request_id=merchant_request_id,
            checkout_request_id=checkout_request_id,
            receipt=receipt,
            raw_payload=payload.model_dump_json(),
        )

        # ----------------------------------------------------
        # 3. Failed M-Pesa transaction
        # ----------------------------------------------------

        if result_code != 0:
            await db.commit()

            return {
                "ResultCode": 0,
                "ResultDesc": "Webhook received successfully",
            }

        # ----------------------------------------------------
        # 4. Validate successful payment
        # ----------------------------------------------------

        if not receipt:
            raise ValueError(
                "Successful callback is missing M-Pesa receipt"
            )

        if amount <= 0:
            raise ValueError(
                "Successful callback contains invalid amount"
            )

        if not phone:
            raise ValueError(
                "Successful callback is missing phone number"
            )

        # ----------------------------------------------------
        # 5. Resolve landlord
        # ----------------------------------------------------

        landlord_id = await resolve_landlord_id(db)

        # ----------------------------------------------------
        # 6. Redis fast-path
        # ----------------------------------------------------

        redis_receipt = receipt

        lock_acquired, redis_token = await acquire_redis_lock(
            receipt
        )

        if not lock_acquired:
            # Redis says this receipt may already be processing.
            # PostgreSQL remains authoritative.

            existing = await db.execute(
                text(
                    """
                    SELECT id
                    FROM payment_processing
                    WHERE mpesa_receipt_number = :receipt
                    LIMIT 1
                    """
                ),
                {
                    "receipt": receipt,
                },
            )

            if existing.scalar_one_or_none():
                await db.commit()

                return {
                    "ResultCode": 0,
                    "ResultDesc": "Duplicate webhook ignored",
                }

            # Redis lock exists, but PostgreSQL has never processed
            # this receipt. Treat Redis as stale.
            lock_acquired = True

        # ----------------------------------------------------
        # 7. PostgreSQL authoritative idempotency claim
        # ----------------------------------------------------

        claimed = await claim_payment(
            db=db,
            receipt=receipt,
            raw_webhook_id=raw_webhook_id,
            landlord_id=landlord_id,
        )

        if not claimed:
            await db.commit()

            return {
                "ResultCode": 0,
                "ResultDesc": "Duplicate webhook ignored",
            }

        # ----------------------------------------------------
        # 8. Financial reconciliation
        # ----------------------------------------------------

        reconciliation = await reconcile_mpesa_payment(
            db=db,
            mpesa_receipt=receipt,
            amount=amount,
            phone=phone,
            landlord_id=landlord_id,
            raw_webhook_id=raw_webhook_id,
            merchant_request_id=merchant_request_id,
            account_ref=None,
        )

        print(
            "Payment reconciliation:",
            reconciliation,
        )

        # ----------------------------------------------------
        # 9. Update processing status
        # ----------------------------------------------------

        processing_status = (
            "COMPLETED"
            if reconciliation["status"] == "MATCHED"
            else "UNASSIGNED"
        )

        await mark_payment_processed(
            db=db,
            receipt=receipt,
            status_value=processing_status,
        )

        # ----------------------------------------------------
        # 10. Commit everything atomically
        # ----------------------------------------------------

        await db.commit()

        # Successful transaction:
        # keep the Redis lock until its TTL expires.
        redis_receipt = None
        redis_token = None

        return {
            "ResultCode": 0,
            "ResultDesc": "Webhook processed successfully",
        }

    except Exception as exc:
        # ----------------------------------------------------
        # 11. Roll back ALL PostgreSQL changes
        # ----------------------------------------------------

        await db.rollback()

        # ----------------------------------------------------
        # 12. Release Redis lock after failure
        # ----------------------------------------------------

        if redis_receipt and redis_token:
            await release_redis_lock(
                receipt=redis_receipt,
                token=redis_token,
            )

        # ----------------------------------------------------
        # 13. Log error
        # ----------------------------------------------------

        print("\n" + "=" * 60)
        print("WEBHOOK ERROR")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60 + "\n")

        return {
            "ResultCode": 1,
            "ResultDesc": (
                f"Internal error recorded: {str(exc)}"
            ),
        }