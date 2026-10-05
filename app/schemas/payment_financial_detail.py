from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_transaction_id: UUID
    invoice_id: UUID
    amount: Decimal
    status: str
    created_at: datetime
    reversed_at: datetime | None


class PaymentCreditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_transaction_id: UUID
    tenant_id: UUID
    amount: Decimal
    status: str
    created_at: datetime
    applied_at: datetime | None
