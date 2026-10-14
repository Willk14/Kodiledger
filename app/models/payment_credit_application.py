from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaymentCreditApplication(Base):
    """Immutable application of a source payment credit to one invoice."""

    __tablename__ = "payment_credit_applications"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    payment_credit_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payment_credits.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invoice_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    application_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="payment_credit_applications_amount_check"),
        UniqueConstraint("application_key", name="uq_payment_credit_application_key"),
        UniqueConstraint(
            "payment_credit_id", "invoice_id",
            name="uq_payment_credit_application_credit_invoice",
        ),
    )
