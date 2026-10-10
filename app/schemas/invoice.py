from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: UUID
    tenant_id: UUID
    invoice_number: str = Field(min_length=1, max_length=100)
    billing_month: date
    rent_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    water_amount: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2
    )
    garbage_amount: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2
    )
    security_amount: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2
    )
    due_date: date

    @field_validator("invoice_number")
    @classmethod
    def normalize_invoice_number(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Invoice number cannot be blank.")
        return normalized


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    unit_id: UUID
    tenant_id: UUID
    invoice_number: str
    billing_month: date
    rent_amount: Decimal
    water_amount: Decimal
    garbage_amount: Decimal
    security_amount: Decimal
    total_amount: Decimal
    due_date: date
    is_paid: bool
    created_at: datetime
