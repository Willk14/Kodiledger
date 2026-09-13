from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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

        await self.db.execute(
            text(
                """
                INSERT INTO unassigned_payments (
                    landlord_id,
                    raw_webhook_id,
                    mpesa_receipt_number,
                    amount,
                    payer_phone,
                    invalid_account_reference
                )
                VALUES (
                    :landlord_id,
                    :raw_webhook_id,
                    :mpesa_receipt,
                    :amount,
                    :payer_phone,
                    :account_reference
                )
                ON CONFLICT (mpesa_receipt_number) DO NOTHING
                """
            ),
            {
                "landlord_id": landlord_id,
                "raw_webhook_id": raw_webhook_id,
                "mpesa_receipt": mpesa_receipt,
                "amount": amount,
                "payer_phone": payer_phone,
                "account_reference": account_reference,
            },
        )

    async def get_by_receipt(
        self,
        mpesa_receipt: str,
    ) -> dict | None:
        """
        Retrieve an unassigned payment by M-Pesa receipt number.
        """

        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    raw_webhook_id,
                    mpesa_receipt_number,
                    amount,
                    payer_phone,
                    invalid_account_reference,
                    created_at
                FROM unassigned_payments
                WHERE mpesa_receipt_number = :receipt
                LIMIT 1
                """
            ),
            {
                "receipt": mpesa_receipt,
            },
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

        This currently treats every row as unresolved because the
        current schema does not yet have explicit resolution fields.
        Those fields will be added in the normalized target schema.
        """

        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    raw_webhook_id,
                    mpesa_receipt_number,
                    amount,
                    payer_phone,
                    invalid_account_reference,
                    created_at
                FROM unassigned_payments
                WHERE landlord_id = :landlord_id
                ORDER BY created_at DESC
                """
            ),
            {
                "landlord_id": landlord_id,
            },
        )

        return [dict(row) for row in result.mappings().all()]

    