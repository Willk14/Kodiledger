from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.landlord import Landlord  # noqa: F401
from app.models.raw_payment_webhook import RawPaymentWebhook  # noqa: F401
from app.models.unit import Unit  # noqa: F401
from app.models.unassigned_payment import UnassignedPayment


class UnassignedPaymentRepository:
    """
    Database access for unassigned M-Pesa payments.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        landlord_id: str,
        raw_webhook_id: str,
        mpesa_receipt: str,
        amount: Decimal,
        payer_phone: str | None,
        account_reference: str | None = None,
    ) -> None:
        """
        Store a successful payment that could not be matched
        to a tenant automatically.
        """

        table = UnassignedPayment.__table__
        statement = (
            insert(table)
            .values(
                landlord_id=landlord_id,
                raw_webhook_id=raw_webhook_id,
                mpesa_receipt_number=mpesa_receipt,
                amount=amount,
                payer_phone=payer_phone,
                invalid_account_reference=account_reference,
            )
            .on_conflict_do_nothing(
                index_elements=[table.c.mpesa_receipt_number]
            )
        )
        await self.db.execute(statement)

    async def get_by_receipt(
        self,
        mpesa_receipt: str,
    ) -> dict | None:
        """
        Retrieve an unassigned payment by M-Pesa receipt number.
        """

        table = UnassignedPayment.__table__
        columns = (
            table.c.id,
            table.c.landlord_id,
            table.c.raw_webhook_id,
            table.c.mpesa_receipt_number,
            table.c.amount,
            table.c.payer_phone,
            table.c.payer_name,
            table.c.invalid_account_reference,
            table.c.is_resolved,
            table.c.resolved_unit_id,
            table.c.resolved_by_user_id,
            table.c.resolved_at,
            table.c.created_at,
        )
        result = await self.db.execute(
            select(*columns)
            .where(table.c.mpesa_receipt_number == mpesa_receipt)
            .limit(1)
        )

        payment = result.mappings().first()

        if not payment:
            return None

        return dict(payment)

    async def list_unresolved(
        self,
        landlord_id: str,
    ) -> list[dict]:
        """
        Return unassigned payments for a landlord.

        Includes rows whose resolution flag is false or NULL.
        """

        table = UnassignedPayment.__table__
        result = await self.db.execute(
            select(
                table.c.id,
                table.c.mpesa_receipt_number,
                table.c.amount,
                table.c.payer_phone,
                table.c.payer_name,
                table.c.invalid_account_reference,
                table.c.created_at,
            )
            .where(
                table.c.landlord_id == landlord_id,
                table.c.is_resolved.is_not(True),
            )
            .order_by(table.c.created_at.desc())
        )

        return [dict(row) for row in result.mappings().all()]

    async def get_by_id_for_update(
        self,
        *,
        payment_id: str,
        landlord_id: str,
    ) -> dict | None:
        table = UnassignedPayment.__table__
        result = await self.db.execute(
            select(
                table.c.id,
                table.c.landlord_id,
                table.c.raw_webhook_id,
                table.c.mpesa_receipt_number,
                table.c.amount,
                table.c.payer_phone,
                table.c.payer_name,
                table.c.invalid_account_reference,
                table.c.is_resolved,
                table.c.resolved_unit_id,
                table.c.resolved_by_user_id,
                table.c.resolved_at,
                table.c.created_at,
            )
            .where(
                table.c.id == payment_id,
                table.c.landlord_id == landlord_id,
            )
            .with_for_update()
            .limit(1)
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def mark_resolved(
        self,
        *,
        payment_id: str,
        landlord_id: str,
        unit_id: str,
        resolved_by_user_id: str,
    ) -> dict | None:
        table = UnassignedPayment.__table__
        result = await self.db.execute(
            update(table)
            .where(
                table.c.id == payment_id,
                table.c.landlord_id == landlord_id,
                table.c.is_resolved.is_not(True),
            )
            .values(
                is_resolved=True,
                resolved_unit_id=unit_id,
                resolved_by_user_id=resolved_by_user_id,
                resolved_at=func.now(),
            )
            .returning(
                table.c.id,
                table.c.is_resolved,
                table.c.resolved_unit_id,
                table.c.resolved_by_user_id,
                table.c.resolved_at,
            )
        )
        row = result.mappings().first()
        return dict(row) if row else None


