from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentTransactionRepository:
    """Persistence operations for normalized payment transactions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        landlord_id: str,
        tenant_id: str | None,
        raw_webhook_id: str | None,
        merchant_request_id: str | None,
        checkout_request_id: str | None,
        mpesa_receipt_number: str,
        payer_phone: str | None,
        payer_name: str | None,
        amount: Decimal,
        payment_method: str,
        status: str = "COMPLETED",
    ) -> dict[str, Any]:
        from app.models.payment_transaction import PaymentTransaction

        # Calculate completed_at in Python instead of using
        # CASE :status = 'COMPLETED' in PostgreSQL.
        completed_at = (
            datetime.now(timezone.utc)
            if status == "COMPLETED"
            else None
        )

        stmt = (
            insert(PaymentTransaction)
            .values(
                landlord_id=landlord_id,
                tenant_id=tenant_id,
                raw_webhook_id=raw_webhook_id,
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                mpesa_receipt_number=mpesa_receipt_number,
                payer_phone=payer_phone,
                payer_name=payer_name,
                amount=amount,
                payment_method=payment_method,
                status=status,
                completed_at=completed_at,
            )
            .on_conflict_do_nothing(
                index_elements=[PaymentTransaction.mpesa_receipt_number],
            )
            .returning(
                PaymentTransaction.id,
                PaymentTransaction.landlord_id,
                PaymentTransaction.tenant_id,
                PaymentTransaction.raw_webhook_id,
                PaymentTransaction.merchant_request_id,
                PaymentTransaction.checkout_request_id,
                PaymentTransaction.mpesa_receipt_number,
                PaymentTransaction.payer_phone,
                PaymentTransaction.payer_name,
                PaymentTransaction.amount,
                PaymentTransaction.payment_method,
                PaymentTransaction.status,
                PaymentTransaction.created_at,
                PaymentTransaction.completed_at,
            )
        )

        result = await self.db.execute(stmt)
        row = result.mappings().first()

        if row:
            return dict(row)

        # Duplicate receipt: return the existing transaction.
        existing = await self.get_by_receipt(mpesa_receipt_number)

        if not existing:
            raise RuntimeError(
                "Payment transaction was not created and could not be found."
            )

        return existing

    async def get_by_receipt(
        self,
        mpesa_receipt_number: str,
    ) -> dict[str, Any] | None:
        from app.models.payment_transaction import PaymentTransaction

        result = await self.db.execute(
            select(
                PaymentTransaction.id,
                PaymentTransaction.landlord_id,
                PaymentTransaction.tenant_id,
                PaymentTransaction.raw_webhook_id,
                PaymentTransaction.merchant_request_id,
                PaymentTransaction.checkout_request_id,
                PaymentTransaction.mpesa_receipt_number,
                PaymentTransaction.payer_phone,
                PaymentTransaction.payer_name,
                PaymentTransaction.amount,
                PaymentTransaction.payment_method,
                PaymentTransaction.status,
                PaymentTransaction.created_at,
                PaymentTransaction.completed_at,
            )
            .where(
                PaymentTransaction.mpesa_receipt_number
                == mpesa_receipt_number
            )
            .limit(1)
        )

        row = result.mappings().first()
        return dict(row) if row else None
