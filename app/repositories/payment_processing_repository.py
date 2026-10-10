from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
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

        from app.models.payment_processing import PaymentProcessing

        stmt = (
            insert(PaymentProcessing)
            .values(
                mpesa_receipt_number=receipt,
                raw_webhook_id=raw_webhook_id,
                landlord_id=landlord_id,
                status="PROCESSING",
            )
            .on_conflict_do_nothing(
                index_elements=[PaymentProcessing.mpesa_receipt_number],
            )
            .returning(PaymentProcessing.id)
        )

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def exists(
        self,
        receipt: str,
    ) -> bool:
        """
        Check whether a payment receipt has already been processed.
        """

        from app.models.payment_processing import PaymentProcessing

        result = await self.db.execute(
            select(PaymentProcessing.id)
            .where(PaymentProcessing.mpesa_receipt_number == receipt)
            .limit(1)
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

        from app.models.payment_processing import PaymentProcessing

        await self.db.execute(
            update(PaymentProcessing)
            .where(PaymentProcessing.mpesa_receipt_number == receipt)
            .values(
                status=status,
                processed_at=func.now(),
            )
        )

    async def mark_assigned(
        self,
        *,
        receipt: str,
        landlord_id: str,
    ) -> None:
        """Move an unmatched successful receipt to completed state."""
        from app.models.payment_processing import PaymentProcessing

        await self.db.execute(
            update(PaymentProcessing)
            .where(
                PaymentProcessing.mpesa_receipt_number == receipt,
                PaymentProcessing.landlord_id == landlord_id,
                PaymentProcessing.status == "UNASSIGNED",
            )
            .values(
                status="COMPLETED",
                processed_at=func.now(),
            )
        )
