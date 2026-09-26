from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.payment_credit import PaymentCredit
    from app.models.invoice import Invoice
    from app.models.landlord import Landlord
    from app.models.ledger_entry import LedgerEntry
    from app.models.unit import Unit


class Tenant(Base):
    __tablename__ = "tenants"

    __table_args__ = (
        Index("idx_tenants_landlord", "landlord_id"),
        Index("idx_tenants_phone", "primary_phone"),
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

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    primary_phone: Mapped[str] = mapped_column(
        String(15),
        nullable=False,
    )

    id_number: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    lease_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    deposit_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        server_default="0.00",
    )

    is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        server_default="true",
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="tenants",
    )

    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="tenants",
    )

    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="tenant",
    )

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="tenant",
    )

    payment_credits: Mapped[list["PaymentCredit"]] = relationship(
        "PaymentCredit",
        back_populates="tenant",
    )
