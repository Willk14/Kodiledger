from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AppUser(Base):
    """KodiLedger account linked to a stable external OIDC identity."""

    __tablename__ = "app_users"
    __table_args__ = (
        UniqueConstraint("identity_issuer", "identity_subject", name="uq_app_users_identity"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    identity_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    identity_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    memberships: Mapped[list["UserMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
