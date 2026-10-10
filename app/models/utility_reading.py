from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import Computed

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.landlord import Landlord
    from app.models.unit import Unit


class UtilityReading(Base):
    __tablename__ = "utility_readings"

    __table_args__ = (
        CheckConstraint(
            "current_reading >= previous_reading",
            name="chk_consumption",
        ),
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
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
    )

    reading_month: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    previous_reading: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    current_reading: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    consumption: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        Computed(
            "current_reading - previous_reading",
            persisted=True,
        ),
    )

    total_water_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    recorded_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="utility_readings",
    )

    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="utility_readings",
    )

    