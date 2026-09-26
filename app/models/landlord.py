from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.models.ledger_entry import LedgerEntry
    from app.models.unassigned_payment import UnassignedPayment
    from app.models.user_device_token import UserDeviceToken
    from app.models.payment_processing import PaymentProcessing
    from app.models.property import Property
    from app.models.tenant import Tenant
    from app.models.unit import Unit
    from app.models.utility_reading import UtilityReading


class Landlord(Base):
    __tablename__ = "landlords"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    phone_number: Mapped[str] = mapped_column(
        String(15),
        unique=True,
        nullable=False,
    )

    kra_pin: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    business_shortcode: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    properties: Mapped[list["Property"]] = relationship(
        "Property",
        back_populates="landlord",
    )

    units: Mapped[list["Unit"]] = relationship(
        "Unit",
        back_populates="landlord",
    )

    tenants: Mapped[list["Tenant"]] = relationship(
        "Tenant",
        back_populates="landlord",
    )

    utility_readings: Mapped[list["UtilityReading"]] = relationship(
        "UtilityReading",
        back_populates="landlord",
    )

    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="landlord",
    )

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="landlord",
    )

    unassigned_payments: Mapped[list["UnassignedPayment"]] = relationship(
        "UnassignedPayment",
        back_populates="landlord",
    )

    device_tokens: Mapped[list["UserDeviceToken"]] = relationship(
        "UserDeviceToken",
        back_populates="landlord",
    )

    payment_processing_records: Mapped[list["PaymentProcessing"]] = relationship(
        "PaymentProcessing",
        back_populates="landlord",
    )
