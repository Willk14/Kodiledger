from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.landlord import Landlord


class UserDeviceToken(Base):
    __tablename__ = "user_device_tokens"

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

    device_token: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )

    platform: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
    )

    landlord: Mapped["Landlord"] = relationship(
        "Landlord",
        back_populates="device_tokens",
    )
