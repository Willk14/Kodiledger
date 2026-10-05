from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.security.roles import Role


class LandlordContextRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: Role
    landlord_id: UUID
    property_count: int = Field(ge=0)
