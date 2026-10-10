from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
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
    ) -> dict[str, Any] | None:
        from app.models.payment_allocation import PaymentAllocation

        stmt = (
            insert(PaymentAllocation)
            .values(
                payment_transaction_id=payment_transaction_id,
                invoice_id=invoice_id,
                amount=amount,
                status=status,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PaymentAllocation.payment_transaction_id,
                    PaymentAllocation.invoice_id,
                ],
            )
            .returning(
                PaymentAllocation.id,
                PaymentAllocation.payment_transaction_id,
                PaymentAllocation.invoice_id,
                PaymentAllocation.amount,
                PaymentAllocation.status,
                PaymentAllocation.created_at,
                PaymentAllocation.reversed_at,
            )
        )
        result = await self.db.execute(
            stmt
        )

        row = result.mappings().first()

        if row:
            return dict(row)

        # The caller must treat a uniqueness conflict as an existing
        # allocation, never as a newly created financial effect.
        return None

    async def get_total_allocated_for_payment(
        self,
        *,
        payment_transaction_id: str,
    ) -> Decimal:
        from app.models.payment_allocation import PaymentAllocation

        result = await self.db.execute(
            select(
                func.coalesce(func.sum(PaymentAllocation.amount), 0)
            ).where(
                PaymentAllocation.payment_transaction_id
                == payment_transaction_id,
                PaymentAllocation.status == "ALLOCATED",
            )
        )
        return Decimal(str(result.scalar_one()))

    async def get(
        self,
        *,
        payment_transaction_id: str,
        invoice_id: str,
    ) -> dict[str, Any] | None:
        from app.models.payment_allocation import PaymentAllocation

        result = await self.db.execute(
            select(
                PaymentAllocation.id,
                PaymentAllocation.payment_transaction_id,
                PaymentAllocation.invoice_id,
                PaymentAllocation.amount,
                PaymentAllocation.status,
                PaymentAllocation.created_at,
                PaymentAllocation.reversed_at,
            )
            .where(
                PaymentAllocation.payment_transaction_id
                == payment_transaction_id,
                PaymentAllocation.invoice_id == invoice_id,
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
    ) -> list[Any]:
        from app.models.payment_allocation import PaymentAllocation
        from app.models.payment_transaction import PaymentTransaction

        result = await self.db.execute(
            select(PaymentAllocation)
            .join(
                PaymentTransaction,
                PaymentTransaction.id == PaymentAllocation.payment_transaction_id,
            )
            .where(
                PaymentAllocation.payment_transaction_id == payment_transaction_id,
                PaymentTransaction.landlord_id == landlord_id,
            )
            .order_by(PaymentAllocation.created_at.asc(), PaymentAllocation.id.asc())
        )
        return list(result.scalars().all())

    async def list_for_payment_transaction(
        self,
        *,
        payment_transaction_id: str,
        landlord_id: str,
    ) -> list:
        from app.models.payment_allocation import PaymentAllocation
        from app.models.payment_transaction import PaymentTransaction

        result = await self.db.execute(
            select(PaymentAllocation)
            .join(
                PaymentTransaction,
                PaymentTransaction.id == PaymentAllocation.payment_transaction_id,
            )
            .where(
                PaymentAllocation.payment_transaction_id == payment_transaction_id,
                PaymentTransaction.landlord_id == landlord_id,
            )
            .order_by(PaymentAllocation.created_at.asc(), PaymentAllocation.id.asc())
        )
        return list(result.scalars().all())
