from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.tenant import TenantCreate, TenantRead


def test_tenant_create_normalizes_names_and_preserves_decimal():
    request = TenantCreate(
        unit_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        full_name="  Ada   Wanjiku ",
        primary_phone="254712345678",
        lease_start_date="2026-01-01",
        deposit_amount="12345.67",
    )

    assert request.full_name == "Ada Wanjiku"
    assert request.lease_start_date == date(2026, 1, 1)
    assert request.deposit_amount == Decimal("12345.67")


@pytest.mark.parametrize(
    "payload",
    [
        {"unit_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "full_name": "A", "primary_phone": "0712345678", "lease_start_date": "2026-01-01"},
        {"unit_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "full_name": "A", "primary_phone": "254712345678", "lease_start_date": "2026-01-01", "deposit_amount": "-0.01"},
        {"unit_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "full_name": "A", "primary_phone": "254712345678", "lease_start_date": "2026-01-01", "landlord_id": "untrusted"},
    ],
)
def test_tenant_create_rejects_invalid_or_untrusted_input(payload):
    with pytest.raises(ValidationError):
        TenantCreate.model_validate(payload)


def test_tenant_response_does_not_expose_government_id():
    response = TenantRead(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        unit_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        full_name="Ada Wanjiku",
        primary_phone="254712345678",
        lease_start_date="2026-01-01",
        deposit_amount="100.00",
        is_active=True,
        created_at="2026-01-01T00:00:00Z",
    )

    assert "id_number" not in response.model_dump()
