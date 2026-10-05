from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.unit import UnitCreate, UnitUpdate


def test_unit_create_defaults_optional_fees_and_trims_unit_number():
    unit = UnitCreate(unit_number="  A-1  ", base_rent="12500.25")

    assert unit.unit_number == "A-1"
    assert unit.base_rent == Decimal("12500.25")
    assert unit.garbage_fee == Decimal("0.00")
    assert unit.security_fee == Decimal("0.00")


@pytest.mark.parametrize(
    "payload",
    [
        {"unit_number": "  ", "base_rent": "100.00"},
        {"unit_number": "A-1", "base_rent": "-0.01"},
        {"unit_number": "A-1", "base_rent": "1.001"},
        {"unit_number": "A-1", "base_rent": "100.00", "landlord_id": "untrusted"},
    ],
)
def test_unit_create_rejects_invalid_or_untrusted_input(payload):
    with pytest.raises(ValidationError):
        UnitCreate.model_validate(payload)


def test_unit_update_rejects_empty_null_and_extra_fields():
    with pytest.raises(ValidationError):
        UnitUpdate.model_validate({"base_rent": None})
    with pytest.raises(ValidationError):
        UnitUpdate.model_validate({"is_occupied": True})
    assert UnitUpdate.model_validate({"base_rent": "1.25"}).model_dump(exclude_unset=True) == {
        "base_rent": Decimal("1.25")
    }
