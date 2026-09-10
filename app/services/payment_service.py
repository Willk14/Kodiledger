from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def reconcile_mpesa_payment(
    db: AsyncSession,
    mpesa_receipt: str,
    amount: Decimal,
    phone: str,
    landlord_id: str,
    raw_webhook_id: str,
    merchant_request_id: str,
    account_ref: str | None = None,
) -> dict:
    """
    Reconcile a successful M-Pesa payment into the financial ledger.

    The caller owns the transaction and is responsible for commit/rollback.
    """

    # 1. Resolve the active tenant
    result = await db.execute(
        text("""
            SELECT
                id,
                landlord_id,
                unit_id
            FROM tenants
            WHERE primary_phone = :phone
              AND landlord_id = :landlord_id
              AND is_active = TRUE
            LIMIT 1
        """),
        {
            "phone": phone,
            "landlord_id": landlord_id,
        },
    )

    tenant = result.mappings().first()

    if tenant:
        # 2. Credit the tenant's ledger
        await db.execute(
            text("""
                INSERT INTO ledger_entries (
                    landlord_id,
                    unit_id,
                    tenant_id,
                    mpesa_receipt_number,
                    merchant_request_id,
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
                    'CREDIT',
                    :amount,
                    'MPESA_STK_PUSH',
                    'COMPLETED',
                    :phone,
                    :account_ref,
                    :description
                )
                ON CONFLICT (mpesa_receipt_number) DO NOTHING
            """),
            {
                "landlord_id": tenant["landlord_id"],
                "unit_id": tenant["unit_id"],
                "tenant_id": tenant["id"],
                "mpesa_receipt": mpesa_receipt,
                "merchant_request_id": merchant_request_id,
                "amount": amount,
                "phone": phone,
                "account_ref": account_ref,
                "description": (
                    f"M-Pesa STK Push Payment Ref: {mpesa_receipt}"
                ),
            },
        )

        return {
            "status": "MATCHED",
            "tenant_id": str(tenant["id"]),
            "merchant_request_id": merchant_request_id,
        }

    # 3. No matching tenant → unassigned payment queue
    await db.execute(
        text("""
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
                :phone,
                :account_ref
            )
            ON CONFLICT (mpesa_receipt_number) DO NOTHING
        """),
        {
            "landlord_id": landlord_id,
            "raw_webhook_id": raw_webhook_id,
            "mpesa_receipt": mpesa_receipt,
            "amount": amount,
            "phone": phone,
            "account_ref": account_ref or "UNKNOWN",
        },
    )

    return {
        "status": "UNASSIGNED",
        "merchant_request_id": merchant_request_id,
    }