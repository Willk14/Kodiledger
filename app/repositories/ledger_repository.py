from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class LedgerRepository:
    """
    Database access for ledger entries.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_credit(
        self,
        landlord_id: str,
        unit_id: str,
        tenant_id: str,
        mpesa_receipt: str,
        merchant_request_id: str,
        payment_transaction_id: str,
        amount: Decimal,
        phone: str,
        account_ref: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        Create a completed CREDIT ledger entry for an M-Pesa payment.

        The ledger entry is explicitly linked to the normalized
        payment_transactions record.
        """

        from app.models.ledger_entry import LedgerEntry

        stmt = (
            insert(LedgerEntry)
            .values(
                landlord_id=landlord_id,
                unit_id=unit_id,
                tenant_id=tenant_id,
                mpesa_receipt_number=mpesa_receipt,
                merchant_request_id=merchant_request_id,
                payment_transaction_id=payment_transaction_id,
                entry_type="CREDIT",
                amount=amount,
                payment_method="MPESA_STK_PUSH",
                status="COMPLETED",
                payer_phone=phone,
                account_reference_used=account_ref,
                description=(
                    description
                    or f"M-Pesa STK Push Payment - "
                       f"Receipt: {mpesa_receipt}"
                ),
            )
            .on_conflict_do_nothing(
                index_elements=[LedgerEntry.mpesa_receipt_number],
            )
        )
        await self.db.execute(stmt)

    async def get_by_receipt(
        self,
        mpesa_receipt: str,
    ) -> dict | None:
        """
        Retrieve a ledger entry by M-Pesa receipt number.
        """

        from app.models.ledger_entry import LedgerEntry

        result = await self.db.execute(
            select(
                LedgerEntry.id,
                LedgerEntry.landlord_id,
                LedgerEntry.unit_id,
                LedgerEntry.tenant_id,
                LedgerEntry.invoice_id,
                LedgerEntry.payment_transaction_id,
                LedgerEntry.mpesa_receipt_number,
                LedgerEntry.merchant_request_id,
                LedgerEntry.entry_type,
                LedgerEntry.amount,
                LedgerEntry.payment_method,
                LedgerEntry.status,
                LedgerEntry.payer_phone,
                LedgerEntry.payer_name,
                LedgerEntry.account_reference_used,
                LedgerEntry.description,
                LedgerEntry.created_at,
            )
            .where(LedgerEntry.mpesa_receipt_number == mpesa_receipt)
            .limit(1)
        )

        ledger_entry = result.mappings().first()

        if not ledger_entry:
            return None

        return dict(ledger_entry)
