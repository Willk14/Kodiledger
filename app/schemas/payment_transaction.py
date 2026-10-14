from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    mpesa_receipt_number: str
    amount: Decimal
    payment_method: str
    status: str
    created_at: datetime
    completed_at: datetime | None
