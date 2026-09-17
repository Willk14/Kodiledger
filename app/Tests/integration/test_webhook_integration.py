from __future__ import annotations

import asyncio

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from app.repositories.outbox_event_repository import OutboxEventRepository
from app.services.outbox_worker import OutboxWorker
from app.services.test_event_publisher import TestEventPublisher
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exact_payment_fully_allocates_invoice_without_payment_credit():
    suffix = uuid4().hex[:12]

    receipt = f"IT-EXACT-{suffix}"
    merchant = f"IT-EXACT-MERCHANT-{suffix}"
    checkout = f"IT-EXACT-CHECKOUT-{suffix}"
    invoice_number = f"IT-EXACT-INVOICE-{suffix}"

    invoice_amount = 200
    payment_amount = 200

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

            assert invoice_paid is True

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

            assert remaining_amount == 0

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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_different_payments_cannot_overallocate_same_invoice():
    suffix = uuid4().hex[:12]

    invoice_number = f"IT-CONCURRENT-INVOICE-{suffix}"

    receipt_a = f"IT-CONCURRENT-A-{suffix}"
    merchant_a = f"IT-CONCURRENT-MERCHANT-A-{suffix}"
    checkout_a = f"IT-CONCURRENT-CHECKOUT-A-{suffix}"

    receipt_b = f"IT-CONCURRENT-B-{suffix}"
    merchant_b = f"IT-CONCURRENT-MERCHANT-B-{suffix}"
    checkout_b = f"IT-CONCURRENT-CHECKOUT-B-{suffix}"

    invoice_amount = 100
    payment_amount = 70
    expected_total_payment = 140
    expected_allocation = 100
    expected_credit = 40

    invoice_id = None
    transaction_ids = []

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

    payload_a = callback_payload(
        receipt_a,
        merchant_a,
        checkout_a,
        payment_amount,
    )

    payload_b = callback_payload(
        receipt_b,
        merchant_b,
        checkout_b,
        payment_amount,
    )

    async def send_payment(payload):
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(
                WEBHOOK_URL,
                json=payload,
            )

    try:
        response_a, response_b = await asyncio.gather(
            send_payment(payload_a),
            send_payment(payload_b),
        )

        assert response_a.status_code == 200
        assert response_b.status_code == 200

        body_a = response_a.json()
        body_b = response_b.json()

        assert body_a["ResultCode"] == 0
        assert body_b["ResultCode"] == 0

        assert body_a["reconciliation"]["status"] == "MATCHED"
        assert body_b["reconciliation"]["status"] == "MATCHED"

        transaction_id_a = body_a["reconciliation"]["payment_transaction_id"]
        transaction_id_b = body_b["reconciliation"]["payment_transaction_id"]

        transaction_ids = [transaction_id_a, transaction_id_b]

        assert transaction_id_a != transaction_id_b

        async with TestSystemSessionLocal() as db:
            allocation_total = await db.scalar(
                text(
                    """
                    SELECT COALESCE(SUM(amount), 0)
                    FROM payment_allocations
                    WHERE invoice_id = :invoice_id
                      AND status = 'ALLOCATED'
                    """
                ),
                {"invoice_id": invoice_id},
            )

            assert allocation_total == expected_allocation
            assert allocation_total <= invoice_amount

            credit_total = await db.scalar(
                text(
                    """
                    SELECT COALESCE(SUM(amount), 0)
                    FROM payment_credits
                    WHERE payment_transaction_id IN (:transaction_id_a, :transaction_id_b)
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            assert credit_total == expected_credit

            transaction_total = await db.scalar(
                text(
                    """
                    SELECT COALESCE(SUM(amount), 0)
                    FROM payment_transactions
                    WHERE id IN (:transaction_id_a, :transaction_id_b)
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            assert transaction_total == expected_total_payment

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

            ledger_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            outbox_count = await db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM outbox_events
                    WHERE aggregate_id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            assert ledger_count == 2
            assert outbox_count == 2

            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE aggregate_id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_credits
                    WHERE payment_transaction_id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_transactions
                    WHERE id IN (
                        :transaction_id_a,
                        :transaction_id_b
                    )
                    """
                ),
                {
                    "transaction_id_a": transaction_id_a,
                    "transaction_id_b": transaction_id_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_processing
                    WHERE mpesa_receipt_number IN (
                        :receipt_a,
                        :receipt_b
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM raw_payment_webhooks
                    WHERE mpesa_receipt_number IN (
                        :receipt_a,
                        :receipt_b
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
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
                        WHERE mpesa_receipt_number IN (
                            :receipt_a,
                            :receipt_b
                        )
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM ledger_entries
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number IN (
                            :receipt_a,
                            :receipt_b
                        )
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_credits
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number IN (
                            :receipt_a,
                            :receipt_b
                        )
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_allocations
                    WHERE payment_transaction_id IN (
                        SELECT id
                        FROM payment_transactions
                        WHERE mpesa_receipt_number IN (
                            :receipt_a,
                            :receipt_b
                        )
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_transactions
                    WHERE mpesa_receipt_number IN (
                        :receipt_a,
                        :receipt_b
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM payment_processing
                    WHERE mpesa_receipt_number IN (
                        :receipt_a,
                        :receipt_b
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
            )

            await db.execute(
                text(
                    """
                    DELETE FROM raw_payment_webhooks
                    WHERE mpesa_receipt_number IN (
                        :receipt_a,
                        :receipt_b
                    )
                    """
                ),
                {
                    "receipt_a": receipt_a,
                    "receipt_b": receipt_b,
                },
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
async def test_outbox_claim_pending_locks_and_returns_event():
    event_id = None
    idempotency_key = f"IT-OUTBOX-CLAIM-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    available_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    try:
        async with TestSystemSessionLocal() as db:
            repository = OutboxEventRepository(db)

            events = await repository.claim_pending(limit=10)

            claimed = next(
                (
                    event
                    for event in events
                    if event["id"] == event_id
                ),
                None,
            )

            assert claimed is not None
            assert claimed["status"] == "PENDING"
            assert claimed["locked_at"] is not None

            await db.rollback()

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_schedule_retry_updates_attempts_and_available_at():
    event_id = None
    idempotency_key = f"IT-OUTBOX-RETRY-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    attempts,
                    available_at,
                    locked_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    try:
        async with TestSystemSessionLocal() as db:
            repository = OutboxEventRepository(db)

            before = await db.scalar(
                text(
                    """
                    SELECT available_at
                    FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )

            await repository.schedule_retry(
                event_id=event_id,
                error="simulated publisher failure",
                delay_seconds=60,
            )

            await db.commit()

            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            status,
                            attempts,
                            available_at,
                            last_error,
                            locked_at
                        FROM outbox_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).mappings().first()

            assert row is not None
            assert row["status"] == "PENDING"
            assert row["attempts"] == 1
            assert row["last_error"] == "simulated publisher failure"
            assert row["locked_at"] is None
            assert row["available_at"] > before

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_mark_published_sets_published_state():
    event_id = None
    idempotency_key = f"IT-OUTBOX-PUBLISHED-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    locked_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    try:
        async with TestSystemSessionLocal() as db:
            repository = OutboxEventRepository(db)

            await repository.mark_published(
                event_id=event_id,
            )

            await db.commit()

            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            status,
                            published_at,
                            last_error,
                            locked_at
                        FROM outbox_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).mappings().first()

            assert row is not None
            assert row["status"] == "PUBLISHED"
            assert row["published_at"] is not None
            assert row["last_error"] is None
            assert row["locked_at"] is None

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_claim_pending_prevents_two_workers_claiming_same_event():
    event_id = None
    idempotency_key = f"IT-OUTBOX-CONCURRENT-CLAIM-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    available_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    db_a = TestSystemSessionLocal()
    db_b = TestSystemSessionLocal()

    try:
        repository_a = OutboxEventRepository(db_a)
        repository_b = OutboxEventRepository(db_b)

        claimed_a, claimed_b = await asyncio.gather(
            repository_a.claim_pending(limit=100),
            repository_b.claim_pending(limit=100),
        )

        events_a = [
            event
            for event in claimed_a
            if event["id"] == event_id
        ]

        events_b = [
            event
            for event in claimed_b
            if event["id"] == event_id
        ]

        assert len(events_a) + len(events_b) == 1

        await db_a.commit()
        await db_b.commit()

    finally:
        await db_a.close()
        await db_b.close()

        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_worker_publishes_pending_event():
    event_id = None
    idempotency_key = f"IT-OUTBOX-WORKER-SUCCESS-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    available_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    try:
        publisher = TestEventPublisher()

        worker = OutboxWorker(
            TestSystemSessionLocal,
            publisher,
            batch_size=100,
        )

        processed = await worker.run_once()

        assert processed >= 1

        published_event = next(
            (
                event
                for event in publisher.published_events
                if event["id"] == event_id
            ),
            None,
        )

        assert published_event is not None

        async with TestSystemSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            status,
                            published_at,
                            attempts,
                            last_error,
                            locked_at
                        FROM outbox_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).mappings().first()

            assert row is not None
            assert row["status"] == "PUBLISHED"
            assert row["published_at"] is not None
            assert row["attempts"] == 0
            assert row["last_error"] is None
            assert row["locked_at"] is None

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_worker_schedules_retry_after_publish_failure():
    event_id = None
    idempotency_key = f"IT-OUTBOX-WORKER-RETRY-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    available_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        before = await db.scalar(
            text(
                """
                SELECT available_at
                FROM outbox_events
                WHERE id = :event_id
                """
            ),
            {"event_id": event_id},
        )
        await db.commit()

    try:
        publisher = TestEventPublisher()
        publisher.fail = True

        worker = OutboxWorker(
            TestSystemSessionLocal,
            publisher,
            batch_size=100,
        )

        processed = await worker.run_once()

        assert processed == 0

        async with TestSystemSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            status,
                            attempts,
                            available_at,
                            last_error,
                            locked_at
                        FROM outbox_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).mappings().first()

            assert row is not None
            assert row["status"] == "PENDING"
            assert row["attempts"] == 1
            assert row["available_at"] > before
            assert row["last_error"] == "Simulated publisher failure"
            assert row["locked_at"] is None

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_worker_marks_event_failed_after_max_attempts():
    event_id = None
    idempotency_key = f"IT-OUTBOX-WORKER-FAILED-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    attempts,
                    available_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    1,
                    CURRENT_TIMESTAMP
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    try:
        publisher = TestEventPublisher()
        publisher.fail = True

        worker = OutboxWorker(
            TestSystemSessionLocal,
            publisher,
            batch_size=100,
            max_attempts=2,
        )

        first_result = await worker.run_once()

        assert first_result == 0

        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE outbox_events
                    SET available_at = CURRENT_TIMESTAMP
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()

        second_result = await worker.run_once()

        assert second_result == 0

        async with TestSystemSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            status,
                            attempts,
                            last_error,
                            locked_at
                        FROM outbox_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).mappings().first()

            assert row is not None
            assert row["status"] == "FAILED"
            assert row["attempts"] == 2
            assert row["last_error"] == "Simulated publisher failure"
            assert row["locked_at"] is None

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_worker_reclaims_stale_locked_event():
    event_id = None
    idempotency_key = f"IT-OUTBOX-STALE-LOCK-{uuid4().hex}"

    async with TestSystemSessionLocal() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO outbox_events (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    payload,
                    status,
                    attempts,
                    available_at,
                    locked_at
                )
                VALUES (
                    'TEST_EVENT',
                    'TEST_AGGREGATE',
                    gen_random_uuid(),
                    :idempotency_key,
                    '{"test": true}'::jsonb,
                    'PENDING',
                    0,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                )
                RETURNING id
                """
            ),
            {"idempotency_key": idempotency_key},
        )

        event_id = result.scalar_one()
        await db.commit()

    try:
        publisher = TestEventPublisher()

        worker = OutboxWorker(
            TestSystemSessionLocal,
            publisher,
            batch_size=100,
            max_attempts=5,
        )

        processed = await worker.run_once()

        assert processed >= 1

        published_event = next(
            (
                event
                for event in publisher.published_events
                if event["id"] == event_id
            ),
            None,
        )

        assert published_event is not None

        async with TestSystemSessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT
                            status,
                            attempts,
                            published_at,
                            locked_at
                        FROM outbox_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).mappings().first()

            assert row is not None
            assert row["status"] == "PUBLISHED"
            assert row["attempts"] == 0
            assert row["published_at"] is not None
            assert row["locked_at"] is None

    finally:
        async with TestSystemSessionLocal() as db:
            await db.execute(
                text(
                    """
                    DELETE FROM outbox_events
                    WHERE id = :event_id
                    """
                ),
                {"event_id": event_id},
            )
            await db.commit()
