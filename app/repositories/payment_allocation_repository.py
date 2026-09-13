from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentAllocationRepository:
    """Persistence operations for payment-to-invoice allocations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        payment_transaction_id: str,
        invoice_id: str,
        amount: Decimal,
        status: str = "ALLOCATED",
    ) -> dict[str, Any]:
        result = await self.db.execute(
            text(
                """
                INSERT INTO payment_allocations (
                    payment_transaction_id,
                    invoice_id,
                    amount,
                    status
                )
                VALUES (
                    :payment_transaction_id,
                    :invoice_id,
                    :amount,
                    :status
                )
                ON CONFLICT (
                    payment_transaction_id,
                    invoice_id
                )
                DO NOTHING
                RETURNING
                    id,
                    payment_transaction_id,
                    invoice_id,
                    amount,
                    status,
                    created_at,
                    reversed_at
                """
            ),
            {
                "payment_transaction_id": payment_transaction_id,
                "invoice_id": invoice_id,
                "amount": amount,
                "status": status,
            },
        )

        row = result.mappings().first()

        if row:
            return dict(row)

        existing = await self.get(
            payment_transaction_id=payment_transaction_id,
            invoice_id=invoice_id,
        )

        if not existing:
            raise RuntimeError(
                "Payment allocation was not created and could not be found."
            )

        return existing

    async def get(
        self,
        *,
        payment_transaction_id: str,
        invoice_id: str,
    ) -> dict[str, Any] | None:
        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    payment_transaction_id,
                    invoice_id,
                    amount,
                    status,
                    created_at,
                    reversed_at
                FROM payment_allocations
                WHERE payment_transaction_id = :payment_transaction_id
                  AND invoice_id = :invoice_id
                LIMIT 1
                """
            ),
            {
                "payment_transaction_id": payment_transaction_id,
                "invoice_id": invoice_id,
            },
        )

        row = result.mappings().first()
        return dict(row) if row else None
