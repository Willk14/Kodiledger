from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    unit_id: UUID
    tenant_id: UUID | None
    invoice_id: UUID | None
    payment_transaction_id: UUID | None
    mpesa_receipt_number: str | None
    entry_type: str
    amount: Decimal
    payment_method: str
    status: str
    description: str
    created_at: datetime | None
