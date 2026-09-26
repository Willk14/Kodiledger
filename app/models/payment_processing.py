from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.landlord import Landlord
    from app.models.raw_payment_webhook import RawPaymentWebhook


class PaymentProcessing(Base):
    __tablename__ = "payment_processing"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PROCESSING','COMPLETED','FAILED','UNASSIGNED')",
            name="chk_payment_processing_status",
        ),
        Index("idx_payment_processing_landlord", "landlord_id"),
        Index("idx_payment_processing_webhook", "raw_webhook_id"),
        Index("idx_payment_processing_receipt", "mpesa_receipt_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )

    mpesa_receipt_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    raw_webhook_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "raw_payment_webhooks.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    landlord_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "landlords.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    raw_webhook: Mapped["RawPaymentWebhook"] = relationship(
        "RawPaymentWebhook",
        back_populates="payment_processing_records",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="payment_processing_records",
    )
