from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


test_system_engine = create_async_engine(
    settings.SYSTEM_DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,
)

TestSystemSessionLocal = async_sessionmaker(
    test_system_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


BASE_URL = "http://127.0.0.1:8000"
WEBHOOK_URL = f"{BASE_URL}/api/v1/webhooks/mpesa"

LANDLORD_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "55555555-5555-5555-5555-555555555555"
UNIT_ID = "33333333-3333-3333-3333-333333333333"
TENANT_PHONE = "254798765432"


def callback_payload(receipt: str, merchant: str, checkout: str, amount: int):
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": merchant,
                "CheckoutRequestID": checkout,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": amount},
                        {
                            "Name": "MpesaReceiptNumber",
                            "Value": receipt,
                        },
                        {
                            "Name": "PhoneNumber",
                            "Value": TENANT_PHONE,
                        },
                    ]
                },
            }
        }
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_matched_webhook_is_idempotent():
    suffix = uuid4().hex[:12]
    receipt = f"IT-RECEIPT-{suffix}"
    merchant = f"IT-MERCHANT-{suffix}"
    checkout = f"IT-CHECKOUT-{suffix}"
    invoice_number = f"IT-INVOICE-{suffix}"
    amount = 150

    invoice_id = None
    raw_webhook_ids: list[str] = []

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO invoices (
                    landlord_id,
                    unit_id,
                    tenant_id,
                    invoice_number,
                    billing_month,
                    rent_amount,
                    water_amount,
                    garbage_amount,
                    security_amount,
                    due_date,
                    is_paid
                )
                VALUES (
                    :landlord_id,
                    :unit_id,
                    :tenant_id,
                    :invoice_number,
                    CURRENT_DATE,
                    :rent_amount,
                    0,
                    0,
                    0,
                    CURRENT_DATE,
                    false
                )
                RETURNING id
                """
            ),
            {
                "landlord_id": LANDLORD_ID,
                "unit_id": UNIT_ID,
                "tenant_id": TENANT_ID,
                "invoice_number": invoice_number,
                "rent_amount": amount,
            },
        )

        invoice_id = str(result.scalar_one())
        await db.commit()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            first = await client.post(
                WEBHOOK_URL,
                json=callback_payload(
                    receipt,
                    merchant,
                    checkout,
                    amount,
                ),
            )

            assert first.status_code == 200
            first_body = first.json()

            assert first_body["ResultCode"] == 0
            assert (
                first_body["ResultDesc"]
                == "Webhook processed successfully"
            )
            assert first_body["reconciliation"]["status"] == "MATCHED"

            second = await client.post(
                WEBHOOK_URL,
                json=callback_payload(
                    receipt,
                    merchant,
                    checkout,
                    amount,
                ),
            )

            assert second.status_code == 200
            second_body = second.json()

            assert second_body["ResultCode"] == 0
            assert (
                second_body["ResultDesc"]
                == "Duplicate webhook ignored"
            )

        async with TestSystemSessionLocal() as db:
            raw_result = await db.execute(
                text(
                    """
                    SELECT id
                    FROM raw_payment_webhooks
                    WHERE mpesa_receipt_number = :receipt
                    ORDER BY created_at
                    """
                ),
                {"receipt": receipt},
            )
            raw_webhook_ids = [
                str(row[0]) for row in raw_result.fetchall()
            ]

            processing_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payment_processing
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )

            transaction_result = await db.execute(
                text(
                    """
                    SELECT id
                    FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )
            transaction_id = transaction_result.scalar_one()

            allocation_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payment_allocations
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": str(transaction_id)},
            )

            ledger_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM ledger_entries
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": str(transaction_id)},
            )

            outbox_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM outbox_events
                    WHERE aggregate_id = :aggregate_id
                    """
                ),
                {"aggregate_id": str(transaction_id)},
            )

            invoice_paid = await db.scalar(
                text(
                    """
                    SELECT is_paid
                    FROM invoices
                    WHERE id = :invoice_id
                    """
                ),
                {"invoice_id": invoice_id},
            )

            assert processing_count == 1
            assert allocation_count == 1
            assert ledger_count == 1
            assert outbox_count == 1
            assert invoice_paid is True

            # Both deliveries are retained as raw audit records.
            assert len(raw_webhook_ids) == 2

    finally:
        async with TestSystemSessionLocal() as db:
            transaction_result = await db.execute(
                text(
                    """
                    SELECT id
                    FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )
            transaction_id = transaction_result.scalar_one_or_none()

            if transaction_id:
                await db.execute(
                    text(
                        """
                        DELETE FROM outbox_events
                        WHERE aggregate_id = :aggregate_id
                        """
                    ),
                    {"aggregate_id": str(transaction_id)},
                )

                await db.execute(
                    text(
                        """
                        DELETE FROM ledger_entries
                        WHERE payment_transaction_id = :transaction_id
                        """
                    ),
                    {"transaction_id": str(transaction_id)},
                )

                await db.execute(
                    text(
                        """
                        DELETE FROM payment_allocations
                        WHERE payment_transaction_id = :transaction_id
                        """
                    ),
                    {"transaction_id": str(transaction_id)},
                )

                await db.execute(
                    text(
                        """
                        DELETE FROM payment_transactions
                        WHERE id = :transaction_id
                        """
                    ),
                    {"transaction_id": str(transaction_id)},
                )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_processing
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM raw_payment_webhooks
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM invoices
                    WHERE id = :invoice_id
                    """
                ),
                {"invoice_id": invoice_id},
            )

            await db.commit()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_successful_webhook_creates_unassigned_payment():
    suffix = uuid4().hex[:12]

    receipt = f"IT-UNASSIGNED-{suffix}"
    merchant = f"IT-UNASSIGNED-MERCHANT-{suffix}"
    checkout = f"IT-UNASSIGNED-CHECKOUT-{suffix}"

    # Deliberately use a phone number that does not belong
    # to an active tenant for Landlord A.
    unmatched_phone = "254700000001"
    amount = 250

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            WEBHOOK_URL,
            json={
                "Body": {
                    "stkCallback": {
                        "MerchantRequestID": merchant,
                        "CheckoutRequestID": checkout,
                        "ResultCode": 0,
                        "ResultDesc": (
                            "The service request is processed successfully."
                        ),
                        "CallbackMetadata": {
                            "Item": [
                                {
                                    "Name": "Amount",
                                    "Value": amount,
                                },
                                {
                                    "Name": "MpesaReceiptNumber",
                                    "Value": receipt,
                                },
                                {
                                    "Name": "PhoneNumber",
                                    "Value": unmatched_phone,
                                },
                            ]
                        },
                    }
                }
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["ResultCode"] == 0
    assert body["ResultDesc"] == "Webhook processed successfully"
    assert body["reconciliation"]["status"] == "UNASSIGNED"
    assert body["reconciliation"]["mpesa_receipt"] == receipt

    transaction_id = body["reconciliation"]["payment_transaction_id"]

    async with TestSystemSessionLocal() as db:
        transaction = await db.execute(
            text(
                """
                SELECT
                    id,
                    tenant_id,
                    amount,
                    status
                FROM payment_transactions
                WHERE mpesa_receipt_number = :receipt
                """
            ),
            {"receipt": receipt},
        )

        row = transaction.mappings().first()

        assert row is not None
        assert str(row["id"]) == transaction_id
        assert row["tenant_id"] is None
        assert row["amount"] == amount
        assert str(row["status"]) == "COMPLETED"

        unassigned = await db.execute(
            text(
                """
                SELECT
                    mpesa_receipt_number,
                    amount,
                    payer_phone,
                    landlord_id
                FROM unassigned_payments
                WHERE mpesa_receipt_number = :receipt
                """
            ),
            {"receipt": receipt},
        )

        unassigned_row = unassigned.mappings().first()

        assert unassigned_row is not None
        assert unassigned_row["amount"] == amount
        assert unassigned_row["payer_phone"] == unmatched_phone
        assert str(unassigned_row["landlord_id"]) == LANDLORD_ID

        allocation_count = await db.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM payment_allocations
                WHERE payment_transaction_id = :transaction_id
                """
            ),
            {"transaction_id": transaction_id},
        )

        ledger_count = await db.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM ledger_entries
                WHERE payment_transaction_id = :transaction_id
                """
            ),
            {"transaction_id": transaction_id},
        )

        outbox_count = await db.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM outbox_events
                WHERE aggregate_id = :transaction_id
                """
            ),
            {"transaction_id": transaction_id},
        )

        assert allocation_count == 0
        assert ledger_count == 0
        assert outbox_count == 0

        processing_status = await db.scalar(
            text(
                """
                SELECT status
                FROM payment_processing
                WHERE mpesa_receipt_number = :receipt
                """
            ),
            {"receipt": receipt},
        )

        assert processing_status == "UNASSIGNED"

        await db.execute(
            text(
                """
                DELETE FROM unassigned_payments
                WHERE mpesa_receipt_number = :receipt
                """
            ),
            {"receipt": receipt},
        )

        await db.execute(
            text(
                """
                DELETE FROM payment_transactions
                WHERE id = :transaction_id
                """
            ),
            {"transaction_id": transaction_id},
        )

        await db.execute(
            text(
                """
                DELETE FROM payment_processing
                WHERE mpesa_receipt_number = :receipt
                """
            ),
            {"receipt": receipt},
        )

        await db.execute(
            text(
                """
                DELETE FROM raw_payment_webhooks
                WHERE mpesa_receipt_number = :receipt
                """
            ),
            {"receipt": receipt},
        )

        await db.commit()

        
@pytest.fixture(scope="session", autouse=True)
async def close_test_engine():
    yield
    await test_system_engine.dispose()
