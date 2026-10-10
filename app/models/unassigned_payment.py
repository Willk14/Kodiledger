from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.landlord import Landlord
    from app.models.raw_payment_webhook import RawPaymentWebhook
    from app.models.unit import Unit


class UnassignedPayment(Base):
    __tablename__ = "unassigned_payments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )

    landlord_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("landlords.id", ondelete="CASCADE"),
        nullable=False,
    )

    raw_webhook_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("raw_payment_webhooks.id"),
    )

    mpesa_receipt_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    payer_phone: Mapped[str] = mapped_column(
        String(15),
        nullable=False,
    )

    payer_name: Mapped[str | None] = mapped_column(
        String(255),
    )

    invalid_account_reference: Mapped[str | None] = mapped_column(
        String(100),
    )

    is_resolved: Mapped[bool | None] = mapped_column(
        server_default="false",
    )

    resolved_unit_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("units.id"),
    )

    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="unassigned_payments",
    )

    raw_webhook: Mapped["RawPaymentWebhook | None"] = relationship(
        "RawPaymentWebhook",
        back_populates="unassigned_payments",
    )

    resolved_unit: Mapped["Unit | None"] = relationship(
        "Unit",
        back_populates="unassigned_payments",
    )
