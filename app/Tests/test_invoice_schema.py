from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.invoice import InvoiceCreate


def valid_invoice_payload() -> dict[str, object]:
    return {
        "unit_id": uuid4(),
        "tenant_id": uuid4(),
        "invoice_number": "  INV-2026-001  ",
        "billing_month": "2026-10-01",
        "rent_amount": "12500.00",
        "due_date": "2026-10-05",
    }


def test_invoice_create_normalizes_number_and_defaults_optional_charges():
    invoice = InvoiceCreate.model_validate(valid_invoice_payload())

    assert invoice.invoice_number == "INV-2026-001"
    assert invoice.billing_month == date(2026, 10, 1)
    assert invoice.rent_amount == Decimal("12500.00")
    assert invoice.water_amount == Decimal("0.00")
    assert invoice.garbage_amount == Decimal("0.00")
    assert invoice.security_amount == Decimal("0.00")


@pytest.mark.parametrize(
    "field",
    ["rent_amount", "water_amount", "garbage_amount", "security_amount"],
)
def test_invoice_create_rejects_negative_amounts(field: str):
    payload = valid_invoice_payload()
    payload[field] = "-0.01"

    with pytest.raises(ValidationError):
        InvoiceCreate.model_validate(payload)


@pytest.mark.parametrize("field", ["landlord_id", "total_amount", "is_paid"])
def test_invoice_create_rejects_server_controlled_fields(field: str):
    payload = valid_invoice_payload()
    payload[field] = "forged"

    with pytest.raises(ValidationError):
        InvoiceCreate.model_validate(payload)


def test_invoice_create_rejects_blank_number_and_invalid_dates():
    blank_number = valid_invoice_payload()
    blank_number["invoice_number"] = "   "
    with pytest.raises(ValidationError):
        InvoiceCreate.model_validate(blank_number)

    invalid_date = valid_invoice_payload()
    invalid_date["due_date"] = "not-a-date"
    with pytest.raises(ValidationError):
        InvoiceCreate.model_validate(invalid_date)
