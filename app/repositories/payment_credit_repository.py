from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentCreditRepository:
    """Persistence operations for tenant payment credits."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_total_for_payment_transaction(
        self,
        *,
        payment_transaction_id: str,
    ) -> Decimal:
        """Sum persisted credits conservatively against their source payment.

        The application currently creates AVAILABLE credits but has no credit
        lifecycle operation that releases the source payment amount. Therefore
        every extant credit row continues to count as consumed, independent of
        status, until such a release is represented explicitly.
        """
        from app.models.payment_credit import PaymentCredit

        result = await self.db.execute(
            select(func.coalesce(func.sum(PaymentCredit.amount), 0)).where(
                PaymentCredit.payment_transaction_id
                == payment_transaction_id,
            )
        )
        return Decimal(str(result.scalar_one()))

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

    async def list_available_for_tenant_for_update(
        self,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Lock available credits in deterministic FIFO order."""
        from app.models.payment_credit import PaymentCredit

        result = await self.db.execute(
            select(PaymentCredit)
            .where(
                PaymentCredit.tenant_id == tenant_id,
                PaymentCredit.status == "AVAILABLE",
            )
            .order_by(PaymentCredit.created_at.asc(), PaymentCredit.id.asc())
            .with_for_update()
        )
        return [
            {
                "id": str(credit.id),
                "payment_transaction_id": str(credit.payment_transaction_id),
                "tenant_id": str(credit.tenant_id),
                "amount": Decimal(str(credit.amount)),
                "status": credit.status,
            }
            for credit in result.scalars().all()
        ]

    async def mark_applied(self, *, payment_credit_id: str) -> None:
        """Set the state projection after the source credit is fully consumed."""
        from app.models.payment_credit import PaymentCredit

        await self.db.execute(
            update(PaymentCredit)
            .where(PaymentCredit.id == payment_credit_id)
            .values(status="APPLIED", applied_at=func.now())
        )

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

    async def list_for_payment_transaction(
        self,
        *,
        payment_transaction_id: str,
        landlord_id: str,
    ) -> list[dict[str, Any]]:
        from app.models.payment_credit import PaymentCredit
        from app.models.payment_credit_application import PaymentCreditApplication
        from app.models.payment_transaction import PaymentTransaction

        applied_amount = (
            select(func.coalesce(func.sum(PaymentCreditApplication.amount), 0))
            .where(
                PaymentCreditApplication.payment_credit_id == PaymentCredit.id
            )
            .correlate(PaymentCredit)
            .scalar_subquery()
        )
        result = await self.db.execute(
            select(
                PaymentCredit.id,
                PaymentCredit.payment_transaction_id,
                PaymentCredit.tenant_id,
                PaymentCredit.amount,
                (PaymentCredit.amount - applied_amount).label("available_amount"),
                PaymentCredit.status,
                PaymentCredit.created_at,
                PaymentCredit.applied_at,
            )
            .join(
                PaymentTransaction,
                PaymentTransaction.id == PaymentCredit.payment_transaction_id,
            )
            .where(
                PaymentCredit.payment_transaction_id == payment_transaction_id,
                PaymentTransaction.landlord_id == landlord_id,
            )
            .order_by(PaymentCredit.created_at.asc(), PaymentCredit.id.asc())
        )
        return [dict(row) for row in result.mappings().all()]
