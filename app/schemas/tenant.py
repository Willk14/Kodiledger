from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: UUID
    full_name: str = Field(min_length=1, max_length=255)
    primary_phone: str = Field(pattern=r"^254\d{9}$", description="Kenyan phone number in 254XXXXXXXXX format")
    id_number: str | None = Field(default=None, max_length=50)
    lease_start_date: date
    deposit_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Full name cannot be blank.")
        return normalized

    @field_validator("id_number")
    @classmethod
    def normalize_id_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    unit_id: UUID
    full_name: str
    primary_phone: str
    lease_start_date: date
    deposit_amount: Decimal
    is_active: bool
    created_at: datetime
