from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.app_user import AppUser


class UserMembership(Base):
    """Application authorization scope assigned by trusted KodiLedger state."""

    __tablename__ = "user_memberships"
    __table_args__ = (
        CheckConstraint(
            "(role IN ('LANDLORD', 'CARETAKER') AND landlord_id IS NOT NULL AND tenant_id IS NULL) "
            "OR (role = 'TENANT' AND landlord_id IS NOT NULL AND tenant_id IS NOT NULL) "
            "OR (role = 'ADMIN' AND landlord_id IS NULL AND tenant_id IS NULL)",
            name="ck_user_memberships_role_scope",
        ),
        CheckConstraint(
            "role IN ('LANDLORD', 'CARETAKER', 'TENANT', 'ADMIN')",
            name="ck_user_memberships_application_role",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "landlord_id"],
            ["tenants.id", "tenants.landlord_id"],
            name="fk_user_memberships_tenant_landlord",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    landlord_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("landlords.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    user: Mapped["AppUser"] = relationship(back_populates="memberships")
