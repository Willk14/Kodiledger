from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.payment_processing import PaymentProcessing
    from app.models.payment_transaction import PaymentTransaction
    from app.models.unassigned_payment import UnassignedPayment


class RawPaymentWebhook(Base):
    __tablename__ = "raw_payment_webhooks"

    __table_args__ = (
        Index(
            "idx_raw_webhooks_receipt",
            "mpesa_receipt_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )

    source_provider: Mapped[str | None] = mapped_column(
        String(50),
        server_default="SAFARICOM_DARAJA",
    )

    merchant_request_id: Mapped[str | None] = mapped_column(
        String(100),
    )

    checkout_request_id: Mapped[str | None] = mapped_column(
        String(100),
    )

    mpesa_receipt_number: Mapped[str | None] = mapped_column(
        String(100),
    )

    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    processed: Mapped[bool | None] = mapped_column(
        Boolean,
        server_default="false",
    )

    error_log: Mapped[str | None] = mapped_column(
        Text,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    payment_processing_records: Mapped[list["PaymentProcessing"]] = relationship(
        "PaymentProcessing",
        back_populates="raw_webhook",
    )

    unassigned_payments: Mapped[list["UnassignedPayment"]] = relationship(
        "UnassignedPayment",
        back_populates="raw_webhook",
    )

    payment_transactions: Mapped[list["PaymentTransaction"]] = relationship(
        "PaymentTransaction",
        back_populates="raw_webhook",
    )
