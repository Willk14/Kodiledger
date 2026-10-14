import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class WebhookRepository:
    """
    Database access for raw payment webhook records.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_raw_webhook(
        self,
        merchant_request_id: str,
        checkout_request_id: str,
        receipt: str | None,
        raw_payload: dict[str, Any],
    ) -> str:
        """
        Persist the original M-Pesa webhook payload.

        Returns:
            UUID of the created raw webhook record.
        """

        result = await self.db.execute(
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
                    CAST(:raw_payload AS JSONB),
                    FALSE
                )
                RETURNING id
                """
            ),
            {
                "merchant_request_id": merchant_request_id,
                "checkout_request_id": checkout_request_id,
                "receipt": receipt,
                "raw_payload": json.dumps(raw_payload),
            },
        )

        return str(result.scalar_one())

    async def mark_processed(self, webhook_id: str) -> None:
        await self.db.execute(
            text("""
                UPDATE raw_payment_webhooks
                SET processed = TRUE, error_log = NULL,
                    locked_at = NULL
                WHERE id = :id
            """),
            {"id": webhook_id},
        )

    async def record_receipt(self, webhook_id: str, receipt: str) -> None:
        """Store the receipt extracted from a successful provider callback."""
        await self.db.execute(
            text("""
                UPDATE raw_payment_webhooks
                SET mpesa_receipt_number = :receipt
                WHERE id = :id
            """),
            {"id": webhook_id, "receipt": receipt},
        )

    async def schedule_retry(
        self, webhook_id: str, error: str, delay_seconds: int
    ) -> None:
        await self.db.execute(
            text("""
                UPDATE raw_payment_webhooks
                SET error_log = :error,
                    attempt_count = attempt_count + 1,
                    next_attempt_at = now() + make_interval(secs => :delay),
                    locked_at = NULL,
                    retry_exhausted_at = CASE WHEN attempt_count + 1 >= 10
                        THEN now() ELSE NULL END
                WHERE id = :id AND processed = FALSE AND retry_exhausted_at IS NULL
            """),
            {"id": webhook_id, "error": error[:4000], "delay": delay_seconds},
        )

    async def claim_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        result = await self.db.execute(
            text("""
                WITH candidates AS (
                    SELECT id FROM raw_payment_webhooks
                    WHERE processed = FALSE
                      AND next_attempt_at <= now()
                      AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
                      AND retry_exhausted_at IS NULL
                      AND COALESCE((raw_payload #>> '{Body,stkCallback,ResultCode}')::int, -1) = 0
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                )
                UPDATE raw_payment_webhooks AS inbox
                SET locked_at = now()
                FROM candidates
                WHERE inbox.id = candidates.id
                RETURNING inbox.id, inbox.raw_payload, inbox.attempt_count
            """),
            {"limit": limit},
        )
        return [dict(row) for row in result.mappings().all()]

