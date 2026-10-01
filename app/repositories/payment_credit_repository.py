from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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
        from app.models.payment_credit import PaymentCredit

        stmt = (
            insert(PaymentCredit)
            .values(
                payment_transaction_id=payment_transaction_id,
                tenant_id=tenant_id,
                amount=amount,
                status=status,
            )
            .returning(
                PaymentCredit.id,
                PaymentCredit.payment_transaction_id,
                PaymentCredit.tenant_id,
                PaymentCredit.amount,
                PaymentCredit.status,
                PaymentCredit.created_at,
                PaymentCredit.applied_at,
            )
        )
        result = await self.db.execute(
            stmt
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
        from app.models.payment_credit import PaymentCredit

        result = await self.db.execute(
            select(
                PaymentCredit.id,
                PaymentCredit.payment_transaction_id,
                PaymentCredit.tenant_id,
                PaymentCredit.amount,
                PaymentCredit.status,
                PaymentCredit.created_at,
                PaymentCredit.applied_at,
            )
            .where(
                PaymentCredit.tenant_id == tenant_id,
                PaymentCredit.status == "AVAILABLE",
            )
            .order_by(PaymentCredit.created_at.asc())
        )

        return [dict(row) for row in result.mappings().all()]

    async def get_by_payment_transaction(
        self,
        *,
        payment_transaction_id: str,
    ) -> dict[str, Any] | None:
        from app.models.payment_credit import PaymentCredit

        result = await self.db.execute(
            select(
                PaymentCredit.id,
                PaymentCredit.payment_transaction_id,
                PaymentCredit.tenant_id,
                PaymentCredit.amount,
                PaymentCredit.status,
                PaymentCredit.created_at,
                PaymentCredit.applied_at,
            )
            .where(
                PaymentCredit.payment_transaction_id
                == payment_transaction_id,
            )
            .limit(1)
        )

        row = result.mappings().first()

        return dict(row) if row else None
