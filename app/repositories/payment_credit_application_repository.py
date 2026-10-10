from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_credit_application import PaymentCreditApplication


class PaymentCreditApplicationRepository:
    """Persistence operations for immutable payment-credit applications."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_total_for_credit(self, *, payment_credit_id: str) -> Decimal:
        result = await self.db.execute(
            select(func.coalesce(func.sum(PaymentCreditApplication.amount), 0)).where(
                PaymentCreditApplication.payment_credit_id == payment_credit_id
            )
        )
        return Decimal(str(result.scalar_one()))

    async def create(
        self,
        *,
        payment_credit_id: str,
        invoice_id: str,
        amount: Decimal,
        application_key: str,
    ) -> dict[str, Any] | None:
        stmt = (
            insert(PaymentCreditApplication)
            .values(
                payment_credit_id=payment_credit_id,
                invoice_id=invoice_id,
                amount=amount,
                application_key=application_key,
            )
            .on_conflict_do_nothing()
            .returning(PaymentCreditApplication.id)
        )
        result = await self.db.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None
