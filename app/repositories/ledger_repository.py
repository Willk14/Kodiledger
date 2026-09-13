from decimal import Decimal

from sqlalchemy import text
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

        await self.db.execute(
            text(
                """
                INSERT INTO ledger_entries (
                    landlord_id,
                    unit_id,
                    tenant_id,
                    mpesa_receipt_number,
                    merchant_request_id,
                    payment_transaction_id,
                    entry_type,
                    amount,
                    payment_method,
                    status,
                    payer_phone,
                    account_reference_used,
                    description
                )
                VALUES (
                    :landlord_id,
                    :unit_id,
                    :tenant_id,
                    :mpesa_receipt,
                    :merchant_request_id,
                    :payment_transaction_id,
                    'CREDIT',
                    :amount,
                    'MPESA_STK_PUSH',
                    'COMPLETED',
                    :phone,
                    :account_ref,
                    :description
                )
                ON CONFLICT (mpesa_receipt_number) DO NOTHING
                """
            ),
            {
                "landlord_id": landlord_id,
                "unit_id": unit_id,
                "tenant_id": tenant_id,
                "mpesa_receipt": mpesa_receipt,
                "merchant_request_id": merchant_request_id,
                "payment_transaction_id": payment_transaction_id,
                "amount": amount,
                "phone": phone,
                "account_ref": account_ref,
                "description": (
                    description
                    or f"M-Pesa STK Push Payment - "
                       f"Receipt: {mpesa_receipt}"
                ),
            },
        )

    async def get_by_receipt(
        self,
        mpesa_receipt: str,
    ) -> dict | None:
        """
        Retrieve a ledger entry by M-Pesa receipt number.
        """

        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    unit_id,
                    tenant_id,
                    invoice_id,
                    payment_transaction_id,
                    mpesa_receipt_number,
                    merchant_request_id,
                    entry_type,
                    amount,
                    payment_method,
                    status,
                    payer_phone,
                    payer_name,
                    account_reference_used,
                    description,
                    created_at
                FROM ledger_entries
                WHERE mpesa_receipt_number = :receipt
                LIMIT 1
                """
            ),
            {
                "receipt": mpesa_receipt,
            },
        )

        ledger_entry = result.mappings().first()

        if not ledger_entry:
            return None

        return dict(ledger_entry)
