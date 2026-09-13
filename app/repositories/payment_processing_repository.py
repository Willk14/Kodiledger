from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentProcessingRepository:
    """
    Database access for payment processing and idempotency state.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def claim_payment(
        self,
        receipt: str,
        raw_webhook_id: str,
        landlord_id: str,
    ) -> bool:
        """
        Attempt to claim a payment receipt.

        PostgreSQL's UNIQUE constraint on mpesa_receipt_number
        is the authoritative idempotency mechanism.

        Returns:
            True  -> payment was successfully claimed.
            False -> receipt already exists.
        """

        result = await self.db.execute(
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

    async def exists(
        self,
        receipt: str,
    ) -> bool:
        """
        Check whether a payment receipt has already been processed.
        """

        result = await self.db.execute(
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

        return result.scalar_one_or_none() is not None

    async def mark_processed(
        self,
        receipt: str,
        status: str,
    ) -> None:
        """
        Update payment processing state and completion timestamp.
        """

        await self.db.execute(
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
                "status": status,
            },
        )

        