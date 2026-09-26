from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import Computed
from app.models.base import Base


if TYPE_CHECKING:
    from app.models.landlord import Landlord
    from app.models.ledger_entry import LedgerEntry
    from app.models.payment_allocation import PaymentAllocation
    from app.models.tenant import Tenant
    from app.models.unit import Unit



class Invoice(Base):
    __tablename__ = "invoices"

    __table_args__ = (
        Index("idx_invoices_landlord", "landlord_id"),
        Index("idx_invoices_tenant", "tenant_id"),
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

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )

    invoice_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    billing_month: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    rent_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    water_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        server_default="0.00",
    )

    garbage_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        server_default="0.00",
    )

    security_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        server_default="0.00",
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        Computed(
            "rent_amount + water_amount + garbage_amount + security_amount",
            persisted=True,
        ),
    )

    due_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    is_paid: Mapped[bool | None] = mapped_column(
        Boolean,
        server_default="false",
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="invoices",
    )

    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="invoices",
    )

    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="invoices",
    )


    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="invoice",
    )

    payment_allocations: Mapped[list["PaymentAllocation"]] = relationship(
        "PaymentAllocation",
        back_populates="invoice",
    )
