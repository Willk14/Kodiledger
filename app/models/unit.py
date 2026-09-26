from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.landlord import Landlord
    from app.models.property import Property
    from app.models.tenant import Tenant
    from app.models.utility_reading import UtilityReading
    from app.models.unassigned_payment import UnassignedPayment


class Unit(Base):
    __tablename__ = "units"

    __table_args__ = (
        CheckConstraint("base_rent >= 0"),
        CheckConstraint("garbage_fee >= 0"),
        CheckConstraint("security_fee >= 0"),
        UniqueConstraint("property_id", "unit_number"),
        Index("idx_units_landlord", "landlord_id"),
        Index("idx_units_property", "property_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )

    property_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )

    landlord_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("landlords.id", ondelete="CASCADE"),
        nullable=False,
    )

    unit_number: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    base_rent: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    garbage_fee: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        server_default="0.00",
    )

    security_fee: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        server_default="0.00",
    )

    water_rate_per_unit: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        server_default="0.00",
    )

    is_occupied: Mapped[bool | None] = mapped_column(
        Boolean,
        server_default="false",
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    property: Mapped["Property"] = relationship(
        "Property",
        back_populates="units",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="units",
    )

    tenants: Mapped[list["Tenant"]] = relationship(
        "Tenant",
        back_populates="unit",
    )

    utility_readings: Mapped[list["UtilityReading"]] = relationship(
        "UtilityReading",
        back_populates="unit",
    )

    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="unit",
    )

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="unit",
    )

    unassigned_payments: Mapped[list["UnassignedPayment"]] = relationship(
        "UnassignedPayment",
        back_populates="resolved_unit",
    )
    