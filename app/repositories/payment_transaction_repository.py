from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
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

        # Calculate completed_at in Python instead of using
        # CASE :status = 'COMPLETED' in PostgreSQL.
        completed_at = (
            datetime.now(timezone.utc)
            if status == "COMPLETED"
            else None
        )

        result = await self.db.execute(
            text(
                """
                INSERT INTO payment_transactions (
                    landlord_id,
                    tenant_id,
                    raw_webhook_id,
                    merchant_request_id,
                    checkout_request_id,
                    mpesa_receipt_number,
                    payer_phone,
                    payer_name,
                    amount,
                    payment_method,
                    status,
                    completed_at
                )
                VALUES (
                    :landlord_id,
                    :tenant_id,
                    :raw_webhook_id,
                    :merchant_request_id,
                    :checkout_request_id,
                    :mpesa_receipt_number,
                    :payer_phone,
                    :payer_name,
                    :amount,
                    :payment_method,
                    CAST(:status AS payment_transaction_status_enum),
                    :completed_at
                )
                ON CONFLICT (mpesa_receipt_number) DO NOTHING
                RETURNING
                    id,
                    landlord_id,
                    tenant_id,
                    raw_webhook_id,
                    merchant_request_id,
                    checkout_request_id,
                    mpesa_receipt_number,
                    payer_phone,
                    payer_name,
                    amount,
                    payment_method,
                    status,
                    created_at,
                    completed_at
                """
            ),
            {
                "landlord_id": landlord_id,
                "tenant_id": tenant_id,
                "raw_webhook_id": raw_webhook_id,
                "merchant_request_id": merchant_request_id,
                "checkout_request_id": checkout_request_id,
                "mpesa_receipt_number": mpesa_receipt_number,
                "payer_phone": payer_phone,
                "payer_name": payer_name,
                "amount": amount,
                "payment_method": payment_method,
                "status": status,
                "completed_at": completed_at,
            },
        )

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

        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    tenant_id,
                    raw_webhook_id,
                    merchant_request_id,
                    checkout_request_id,
                    mpesa_receipt_number,
                    payer_phone,
                    payer_name,
                    amount,
                    payment_method,
                    status,
                    created_at,
                    completed_at
                FROM payment_transactions
                WHERE mpesa_receipt_number = :mpesa_receipt_number
                LIMIT 1
                """
            ),
            {
                "mpesa_receipt_number": mpesa_receipt_number,
            },
        )

        row = result.mappings().first()
        return dict(row) if row else None