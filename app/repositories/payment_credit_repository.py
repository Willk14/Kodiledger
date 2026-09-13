from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentCreditRepository:
    """Persistence operations for tenant payment credits."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        payment_transaction_id: str,
        tenant_id: str,
        amount: Decimal,
        status: str = "AVAILABLE",
    ) -> dict[str, Any]:
        result = await self.db.execute(
            text(
                """
                INSERT INTO payment_credits (
                    payment_transaction_id,
                    tenant_id,
                    amount,
                    status
                )
                VALUES (
                    :payment_transaction_id,
                    :tenant_id,
                    :amount,
                    :status
                )
                RETURNING
                    id,
                    payment_transaction_id,
                    tenant_id,
                    amount,
                    status,
                    created_at,
                    applied_at
                """
            ),
            {
                "payment_transaction_id": payment_transaction_id,
                "tenant_id": tenant_id,
                "amount": amount,
                "status": status,
            },
        )

        row = result.mappings().first()

        if not row:
            raise RuntimeError("Payment credit was not created.")

        return dict(row)

    async def get_available_for_tenant(
        self,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    payment_transaction_id,
                    tenant_id,
                    amount,
                    status,
                    created_at,
                    applied_at
                FROM payment_credits
                WHERE tenant_id = :tenant_id
                  AND status = 'AVAILABLE'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": tenant_id},
        )

        return [dict(row) for row in result.mappings().all()]

    async def get_by_payment_transaction(
        self,
        *,
        payment_transaction_id: str,
    ) -> dict[str, Any] | None:
        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    payment_transaction_id,
                    tenant_id,
                    amount,
                    status,
                    created_at,
                    applied_at
                FROM payment_credits
                WHERE payment_transaction_id = :payment_transaction_id
                LIMIT 1
                """
            ),
            {
                "payment_transaction_id": payment_transaction_id,
            },
        )

        row = result.mappings().first()

        return dict(row) if row else None
