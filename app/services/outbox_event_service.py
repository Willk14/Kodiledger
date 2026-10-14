from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from app.repositories.outbox_event_repository import (
    OutboxEventRepository,
)


class OutboxEventService:
    def __init__(
        self,
        repository: OutboxEventRepository,
    ) -> None:
        self.repository = repository

    async def record_payment_processed(
        self,
        *,
        payment_transaction_id: str,
        payment_receipt: str,
        amount: Decimal,
        tenant_id: str | None,
        landlord_id: str,
        allocation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = {
            "payment_transaction_id": payment_transaction_id,
            "mpesa_receipt_number": payment_receipt,
            "amount": str(amount),
            "tenant_id": tenant_id,
            "landlord_id": landlord_id,
            "allocation": self._serialize(allocation),
        }

        return await self.repository.create(
            event_type="PAYMENT_PROCESSED",
            aggregate_type="PAYMENT_TRANSACTION",
            aggregate_id=UUID(payment_transaction_id),
            idempotency_key=(
                f"PAYMENT_PROCESSED:{payment_transaction_id}"
            ),
            payload=payload,
        )

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)

        if isinstance(value, UUID):
            return str(value)

        if isinstance(value, dict):
            return {
                str(key): OutboxEventService._serialize(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [
                OutboxEventService._serialize(item)
                for item in value
            ]

        return value