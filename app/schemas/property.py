from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PropertyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    county: str = Field(min_length=1, max_length=100)
    town_location: str | None = Field(default=None, max_length=255)
    total_units: int = Field(ge=1)

    @field_validator("name", "county", "town_location")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized


class PropertyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    county: str
    town_location: str | None
    total_units: int
    created_at: datetime | None
