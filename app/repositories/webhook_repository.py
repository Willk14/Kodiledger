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
                    TRUE
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

    