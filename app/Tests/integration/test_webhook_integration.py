from __future__ import annotations

import asyncio

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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_webhook_is_audited_without_financial_processing():
    suffix = uuid4().hex[:12]

    merchant = f"IT-FAILED-MERCHANT-{suffix}"
    checkout = f"IT-FAILED-CHECKOUT-{suffix}"
    receipt = f"IT-FAILED-{suffix}"

    result_code = 1032
    result_desc = "Request cancelled by user"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                WEBHOOK_URL,
                json={
                    "Body": {
                        "stkCallback": {
                            "MerchantRequestID": merchant,
                            "CheckoutRequestID": checkout,
                            "ResultCode": result_code,
                            "ResultDesc": result_desc,
                        }
                    }
                },
            )

        assert response.status_code == 200

        body = response.json()

        # The webhook endpoint acknowledges receipt of the failed callback.
        assert body["ResultCode"] == 0

        async with TestSystemSessionLocal() as db:
            raw_result = await db.execute(
                text(
                    """
                    SELECT
                        id,
                        merchant_request_id,
                        checkout_request_id,
                        mpesa_receipt_number,
                        raw_payload,
                        processed,
                        error_log
                    FROM raw_payment_webhooks
                    WHERE merchant_request_id = :merchant
                      AND checkout_request_id = :checkout
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "merchant": merchant,
                    "checkout": checkout,
                },
            )

            raw_row = raw_result.mappings().first()

            assert raw_row is not None
            assert raw_row["merchant_request_id"] == merchant
            assert raw_row["checkout_request_id"] == checkout
            assert raw_row["processed"] is True

            # Failed callbacks do not contain successful-payment metadata.
            assert raw_row["mpesa_receipt_number"] is None

            raw_payload = raw_row["raw_payload"]

            assert raw_payload["Body"]["stkCallback"]["ResultCode"] == result_code
            assert (
                raw_payload["Body"]["stkCallback"]["ResultDesc"]
                == result_desc
            )

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

            transaction_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )

            assert processing_count == 0
            assert transaction_count == 0

            await db.execute(
                text(
                    """
                    DELETE FROM raw_payment_webhooks
                    WHERE merchant_request_id = :merchant
                      AND checkout_request_id = :checkout
                    """
                ),
                {
                    "merchant": merchant,
                    "checkout": checkout,
                },
            )

            await db.commit()

    except Exception:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM raw_payment_webhooks
                    WHERE merchant_request_id = :merchant
                      AND checkout_request_id = :checkout
                    """
                ),
                {
                    "merchant": merchant,
                    "checkout": checkout,
                },
            )
            await db.commit()
        raise


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_duplicate_webhooks_create_one_financial_chain():
    suffix = uuid4().hex[:12]

    receipt = f"IT-CONCURRENT-{suffix}"
    merchant = f"IT-CONCURRENT-MERCHANT-{suffix}"
    checkout = f"IT-CONCURRENT-CHECKOUT-{suffix}"
    invoice_number = f"IT-CONCURRENT-INVOICE-{suffix}"
    amount = 150

    invoice_id = None

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

    payload = callback_payload(
        receipt,
        merchant,
        checkout,
        amount,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            responses = await asyncio.gather(
                client.post(WEBHOOK_URL, json=payload),
                client.post(WEBHOOK_URL, json=payload),
            )

        assert len(responses) == 2
        assert all(response.status_code == 200 for response in responses)

        bodies = [response.json() for response in responses]

        result_descs = {body["ResultDesc"] for body in bodies}

        assert "Webhook processed successfully" in result_descs
        assert "Duplicate webhook ignored" in result_descs

        async with TestSystemSessionLocal() as db:
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

            transaction_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
            )

            allocation_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            ledger_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            outbox_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM outbox_events
                    WHERE aggregate_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
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
            assert transaction_count == 1
            assert allocation_count == 1
            assert ledger_count == 1
            assert outbox_count == 1
            assert invoice_paid is True

            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
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

    except Exception:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
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

            if invoice_id:
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

        raise


@pytest.mark.integration
@pytest.mark.asyncio
async def test_overpayment_allocates_invoice_and_creates_payment_credit():
    suffix = uuid4().hex[:12]

    receipt = f"IT-OVERPAYMENT-{suffix}"
    merchant = f"IT-OVERPAYMENT-MERCHANT-{suffix}"
    checkout = f"IT-OVERPAYMENT-CHECKOUT-{suffix}"
    invoice_number = f"IT-OVERPAYMENT-INVOICE-{suffix}"

    invoice_amount = 150
    payment_amount = 200
    expected_credit = 50

    invoice_id = None

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
                "rent_amount": invoice_amount,
            },
        )

        invoice_id = str(result.scalar_one())
        await db.commit()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                WEBHOOK_URL,
                json=callback_payload(
                    receipt,
                    merchant,
                    checkout,
                    payment_amount,
                ),
            )

        assert response.status_code == 200

        body = response.json()

        assert body["ResultCode"] == 0
        assert body["ResultDesc"] == "Webhook processed successfully"
        assert body["reconciliation"]["status"] == "MATCHED"

        transaction_id = body["reconciliation"]["payment_transaction_id"]

        async with TestSystemSessionLocal() as db:
            allocation_result = await db.execute(
                text(
                    """
                    SELECT
                        amount,
                        status,
                        invoice_id
                    FROM payment_allocations
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            allocation = allocation_result.mappings().first()

            assert allocation is not None
            assert allocation["amount"] == invoice_amount
            assert str(allocation["status"]) == "ALLOCATED"
            assert str(allocation["invoice_id"]) == invoice_id

            credit_result = await db.execute(
                text(
                    """
                    SELECT
                        amount,
                        status,
                        tenant_id,
                        payment_transaction_id
                    FROM payment_credits
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            credit = credit_result.mappings().first()

            assert credit is not None
            assert credit["amount"] == expected_credit
            assert str(credit["status"]) == "AVAILABLE"
            assert str(credit["tenant_id"]) == TENANT_ID
            assert str(credit["payment_transaction_id"]) == transaction_id

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

            assert invoice_paid is True

            transaction_amount = await db.scalar(
                text(
                    """
                    SELECT amount
                    FROM payment_transactions
                    WHERE id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            assert transaction_amount == payment_amount

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

            assert ledger_count == 1
            assert outbox_count == 1

            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_credits
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
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

    except Exception:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_credits
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
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

            if invoice_id:
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

        raise


@pytest.mark.integration
@pytest.mark.asyncio
async def test_partial_payment_allocates_invoice_without_payment_credit():
    suffix = uuid4().hex[:12]

    receipt = f"IT-PARTIAL-{suffix}"
    merchant = f"IT-PARTIAL-MERCHANT-{suffix}"
    checkout = f"IT-PARTIAL-CHECKOUT-{suffix}"
    invoice_number = f"IT-PARTIAL-INVOICE-{suffix}"

    invoice_amount = 200
    payment_amount = 150

    invoice_id = None
    transaction_id = None

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
                "rent_amount": invoice_amount,
            },
        )

        invoice_id = str(result.scalar_one())
        await db.commit()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                WEBHOOK_URL,
                json=callback_payload(
                    receipt,
                    merchant,
                    checkout,
                    payment_amount,
                ),
            )

        assert response.status_code == 200

        body = response.json()

        assert body["ResultCode"] == 0
        assert body["ResultDesc"] == "Webhook processed successfully"
        assert body["reconciliation"]["status"] == "MATCHED"

        transaction_id = body["reconciliation"]["payment_transaction_id"]

        async with TestSystemSessionLocal() as db:
            allocation_result = await db.execute(
                text(
                    """
                    SELECT
                        amount,
                        status,
                        invoice_id
                    FROM payment_allocations
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            allocation = allocation_result.mappings().first()

            assert allocation is not None
            assert allocation["amount"] == payment_amount
            assert str(allocation["status"]) == "ALLOCATED"
            assert str(allocation["invoice_id"]) == invoice_id

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

            assert invoice_paid is False

            remaining_amount = await db.scalar(
                text(
                    """
                    SELECT
                        (
                            rent_amount
                            + water_amount
                            + garbage_amount
                            + security_amount
                        ) - COALESCE(
                            (
                                SELECT SUM(pa.amount)
                                FROM payment_allocations pa
                                WHERE pa.invoice_id = invoices.id
                                  AND pa.status = 'ALLOCATED'
                            ),
                            0
                        )
                    FROM invoices
                    WHERE id = :invoice_id
                    """
                ),
                {"invoice_id": invoice_id},
            )

            assert remaining_amount == invoice_amount - payment_amount

            credit_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payment_credits
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            assert credit_count == 0

            transaction_amount = await db.scalar(
                text(
                    """
                    SELECT amount
                    FROM payment_transactions
                    WHERE id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            assert transaction_amount == payment_amount

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

            assert ledger_count == 1
            assert outbox_count == 1

            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction_id},
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

    except Exception:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number = :receipt
                    )
                    """
                ),
                {"receipt": receipt},
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_transactions
                    WHERE mpesa_receipt_number = :receipt
                    """
                ),
                {"receipt": receipt},
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

            if invoice_id:
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

        raise
