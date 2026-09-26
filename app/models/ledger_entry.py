from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import CheckConstraint

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.landlord import Landlord
    from app.models.tenant import Tenant
    from app.models.unit import Unit


payment_status_enum = ENUM(
    "INITIATED",
    "PENDING",
    "COMPLETED",
    "FAILED",
    "REVERSED",
    name="payment_status_enum",
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

ledger_entry_type_enum = ENUM(
    "DEBIT",
    "CREDIT",
    name="ledger_entry_type_enum",
    create_type=False,
)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ledger_entries_amount_check",
        ),
        Index("idx_ledger_landlord", "landlord_id"),
        Index("idx_ledger_unit", "unit_id"),
        Index("idx_ledger_tenant", "tenant_id"),
        Index("idx_ledger_receipt", "mpesa_receipt_number"),
    )


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

    unit_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=False,
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
    )

    invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
    )

    mpesa_receipt_number: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
    )

    merchant_request_id: Mapped[str | None] = mapped_column(
        String(100),
    )

    entry_type: Mapped[str] = mapped_column(
        ledger_entry_type_enum,
        nullable=False,
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
        payment_status_enum,
        nullable=False,
        server_default="INITIATED",
    )

    payer_phone: Mapped[str | None] = mapped_column(
        String(15),
    )

    payer_name: Mapped[str | None] = mapped_column(
        String(255),
    )

    account_reference_used: Mapped[str | None] = mapped_column(
        String(100),
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="ledger_entries",
    )

    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="ledger_entries",
    )

    tenant: Mapped["Tenant | None"] = relationship(
        "Tenant",
        back_populates="ledger_entries",
    )

    invoice: Mapped["Invoice | None"] = relationship(
        "Invoice",
        back_populates="ledger_entries",
    )
