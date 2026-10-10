from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UnassignedPaymentResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID


class UnassignedPaymentRead(BaseModel):
    id: UUID
    mpesa_receipt_number: str
    amount: Decimal
    payer_phone: str
    payer_name: str | None
    invalid_account_reference: str | None
    created_at: datetime | None


class UnassignedPaymentResolutionRead(BaseModel):
    id: UUID
    payment_transaction_id: UUID
    mpesa_receipt_number: str
    tenant_id: UUID
    unit_id: UUID
    amount: Decimal
    allocation: dict[str, Any]
    outbox_event_id: UUID
    resolved_at: datetime
