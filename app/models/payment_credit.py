from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.payment_transaction import PaymentTransaction
    from app.models.tenant import Tenant


class PaymentCredit(Base):
    __tablename__ = "payment_credits"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    payment_transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "payment_transactions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "tenants.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'AVAILABLE'"),
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    applied_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="payment_credits_amount_check",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE', 'APPLIED', 'REFUNDED', 'CANCELLED')",
            name="payment_credits_status_check",
        ),
        Index(
            "idx_payment_credits_tenant",
            "tenant_id",
        ),
        Index(
            "idx_payment_credits_payment_transaction",
            "payment_transaction_id",
        ),
        Index(
            "idx_payment_credits_status",
            "status",
        ),
    )

    payment_transaction: Mapped["PaymentTransaction"] = relationship(
        "PaymentTransaction",
        back_populates="payment_credits",
    )

    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="payment_credits",
    )
