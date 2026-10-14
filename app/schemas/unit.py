from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_number: str = Field(min_length=1, max_length=50)
    base_rent: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    garbage_fee: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    security_fee: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    water_rate_per_unit: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)

    @field_validator("unit_number")
    @classmethod
    def strip_unit_number(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Unit number cannot be blank.")
        return normalized


class UnitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_number: str | None = Field(default=None, min_length=1, max_length=50)
    base_rent: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    garbage_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    security_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    water_rate_per_unit: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)

    @field_validator(
        "unit_number",
        "base_rent",
        "garbage_fee",
        "security_fee",
        "water_rate_per_unit",
        mode="before",
    )
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Fields cannot be null.")
        return value

    @field_validator("unit_number")
    @classmethod
    def strip_unit_number(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Unit number cannot be blank.")
        return normalized


class UnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID
    unit_number: str
    base_rent: Decimal
    garbage_fee: Decimal
    security_fee: Decimal
    water_rate_per_unit: Decimal
    is_occupied: bool
    created_at: datetime
