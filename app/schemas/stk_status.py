from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StkRequestQueueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    checkout_request_id: str
    status: str
    query_count: int
    created_at: datetime
    last_queried_at: datetime | None


class StkRequestQueuePage(BaseModel):
    items: list[StkRequestQueueItem]
    total: int
    limit: int
    offset: int
