from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.payment_transaction import PaymentTransaction


payment_allocation_status_enum = ENUM(
    "ALLOCATED",
    "REVERSED",
    name="payment_allocation_status_enum",
    create_type=False,
)


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"

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

    invoice_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "invoices.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        payment_allocation_status_enum,
        nullable=False,
        server_default=text("'ALLOCATED'"),
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    reversed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="chk_payment_allocations_amount",
        ),
        UniqueConstraint(
            "payment_transaction_id",
            "invoice_id",
            name="uq_payment_allocation_payment_invoice",
        ),
        Index(
            "idx_payment_allocations_payment",
            "payment_transaction_id",
        ),
        Index(
            "idx_payment_allocations_invoice",
            "invoice_id",
        ),
        Index(
            "idx_payment_allocations_status",
            "status",
        ),
    )

    payment_transaction: Mapped["PaymentTransaction"] = relationship(
        "PaymentTransaction",
        back_populates="payment_allocations",
    )

    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="payment_allocations",
    )
