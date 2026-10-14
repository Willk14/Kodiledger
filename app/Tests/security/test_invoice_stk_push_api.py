from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.controllers.payments as payments_module
from app.configs.database import get_system_db
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.stk_push_request_repository import StkPushRequestRepository
from app.core.rate_limiter import enforce_stk_push_rate_limit
from app.security.dependencies import get_current_principal
from app.security.principals import AuthenticatedContext
from app.security.rls import get_rls_db
from app.security.roles import Role


@pytest.fixture
def invoice_payment_api(monkeypatch):
    landlord_id = str(uuid4())
    invoice_id = str(uuid4())
    principal = AuthenticatedContext(
        user_id=str(uuid4()), role=Role.LANDLORD, landlord_id=landlord_id
    )
    db = AsyncMock()
    system_db = AsyncMock()
    invoice_repository = AsyncMock()
    invoice_repository.get_stk_payment_context.return_value = {
        "id": invoice_id,
        "tenant_id": str(uuid4()),
        "unit_id": str(uuid4()),
        "is_paid": False,
        "invoice_number": "INV-2026-001",
        "total_amount": Decimal("12000.00"),
        "amount_due": Decimal("12000.00"),
    }
    stk_repository = AsyncMock()

    monkeypatch.setattr(
        payments_module, "InvoiceRepository", lambda _db: invoice_repository
    )
    monkeypatch.setattr(
        payments_module, "StkPushRequestRepository", lambda _db: stk_repository
    )
    monkeypatch.setattr(
        payments_module.payment_initiation_service,
        "initiate_mpesa_stk_push",
        AsyncMock(return_value={
            "MerchantRequestID": "merchant-1",
            "CheckoutRequestID": "checkout-1",
            "ResponseCode": "0",
            "ResponseDescription": "Accepted",
            "CustomerMessage": "Prompt sent",
        }),
    )

    api = FastAPI()
    api.include_router(payments_module.router, prefix="/api/v1")
    api.dependency_overrides[get_current_principal] = lambda: principal

    async def override_rls_db():
        return db

    async def override_system_db():
        yield system_db

    async def allow_rate_limit():
        return None

    api.dependency_overrides[get_rls_db] = override_rls_db
    api.dependency_overrides[get_system_db] = override_system_db
    api.dependency_overrides[enforce_stk_push_rate_limit] = allow_rate_limit
    return (
        TestClient(api), invoice_id, invoice_repository, system_db, stk_repository
    )


def test_invoice_stk_push_uses_outstanding_invoice_amount(invoice_payment_api):
    client, invoice_id, invoice_repository, system_db, stk_repository = invoice_payment_api

    response = client.post(
        f"/api/v1/payments/invoices/{invoice_id}/stk-push",
        json={"phone_number": "254712345678"},
    )

    assert response.status_code == 200
    assert response.json()["CheckoutRequestID"] == "checkout-1"
    payments_module.payment_initiation_service.initiate_mpesa_stk_push.assert_awaited_once_with(
        phone_number="254712345678",
        amount=12000,
        account_reference="INV-2026-001",
        transaction_description="Rent INV-2026-001",
    )
    invoice_repository.get_stk_payment_context.assert_awaited_once()
    stk_repository.record_initiation.assert_awaited_once_with(
        "merchant-1", "checkout-1", invoice_id
    )
    system_db.commit.assert_awaited_once()


def test_paid_invoice_rejects_stk_without_calling_provider(invoice_payment_api):
    client, invoice_id, invoice_repository, _system_db, _stk_repository = invoice_payment_api
    invoice_repository.get_stk_payment_context.return_value["is_paid"] = True

    response = client.post(
        f"/api/v1/payments/invoices/{invoice_id}/stk-push",
        json={"phone_number": "254712345678"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Invoice is already paid."
    payments_module.payment_initiation_service.initiate_mpesa_stk_push.assert_not_awaited()
