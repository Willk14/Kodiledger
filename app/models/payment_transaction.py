from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import ENUM, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.raw_payment_webhook import RawPaymentWebhook
    from app.models.payment_credit import PaymentCredit
    from app.models.payment_allocation import PaymentAllocation


payment_transaction_status_enum = ENUM(
    "PENDING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "REVERSED",
    name="payment_transaction_status_enum",
    create_type=False,
)

payment_method_enum = ENUM(
    "MPESA_STK_PUSH",
    "MPESA_C2B_PAYBILL",
    "MPESA_TILL",
    "BANK_TRANSFER",
    "CASH",
    "CHEQUE",
    name="payment_method_enum",
    create_type=False,
)


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    landlord_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("landlords.id", ondelete="RESTRICT"),
        nullable=False,
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )

    raw_webhook_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_payment_webhooks.id", ondelete="SET NULL"),
        nullable=True,
    )

    merchant_request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    checkout_request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    mpesa_receipt_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )

    payer_phone: Mapped[str | None] = mapped_column(
        String(15),
        nullable=True,
    )

    payer_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    payment_method: Mapped[str] = mapped_column(
        payment_method_enum,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        payment_transaction_status_enum,
        nullable=False,
        server_default=text("'PENDING'"),
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="chk_payment_transactions_amount",
        ),
        Index(
            "idx_payment_transactions_landlord",
            "landlord_id",
        ),
        Index(
            "idx_payment_transactions_tenant",
            "tenant_id",
        ),
        Index(
            "idx_payment_transactions_raw_webhook",
            "raw_webhook_id",
        ),
        Index(
            "idx_payment_transactions_merchant_request",
            "merchant_request_id",
        ),
        Index(
            "idx_payment_transactions_checkout_request",
            "checkout_request_id",
        ),
    )

    raw_webhook: Mapped["RawPaymentWebhook | None"] = relationship(
        "RawPaymentWebhook",
        back_populates="payment_transactions",
    )

    payment_allocations: Mapped[list["PaymentAllocation"]] = relationship(
        "PaymentAllocation",
        back_populates="payment_transaction",
    )

    payment_credits: Mapped[list["PaymentCredit"]] = relationship(
        "PaymentCredit",
        back_populates="payment_transaction",
    )

    