from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OutboxEventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        query = text(
            """
            INSERT INTO outbox_events (
                event_type,
                aggregate_type,
                aggregate_id,
                idempotency_key,
                payload
            )
            VALUES (
                :event_type,
                :aggregate_type,
                :aggregate_id,
                :idempotency_key,
                CAST(:payload AS JSONB)
            )
            ON CONFLICT (idempotency_key)
            DO NOTHING
            RETURNING
                id,
                event_type,
                aggregate_type,
                aggregate_id,
                idempotency_key,
                payload,
                status,
                attempts,
                available_at,
                published_at,
                last_error,
                created_at
            """
        )

        result = await self.db.execute(
            query,
            {
                "event_type": event_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "idempotency_key": idempotency_key,
                "payload": json.dumps(payload),
            },
        )

        row = result.mappings().first()

        if row:
            return dict(row)

        existing_query = text(
            """
            SELECT
                id,
                event_type,
                aggregate_type,
                aggregate_id,
                idempotency_key,
                payload,
                status,
                attempts,
                available_at,
                published_at,
                last_error,
                created_at
            FROM outbox_events
            WHERE idempotency_key = :idempotency_key
            """
        )

        existing_result = await self.db.execute(
            existing_query,
            {"idempotency_key": idempotency_key},
        )

        existing_row = existing_result.mappings().first()

        if not existing_row:
            raise RuntimeError(
                "Outbox event could not be inserted or retrieved"
            )

        return dict(existing_row)

    async def get_pending(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = text(
            """
            SELECT
                id,
                event_type,
                aggregate_type,
                aggregate_id,
                idempotency_key,
                payload,
                status,
                attempts,
                available_at,
                published_at,
                last_error,
                created_at
            FROM outbox_events
            WHERE status = 'PENDING'
              AND available_at <= CURRENT_TIMESTAMP
            ORDER BY created_at
            LIMIT :limit
            """
        )

        result = await self.db.execute(
            query,
            {"limit": limit},
        )

        return [dict(row) for row in result.mappings().all()]

    async def mark_published(
        self,
        *,
        event_id: UUID,
    ) -> None:
        query = text(
            """
            UPDATE outbox_events
            SET
                status = 'PUBLISHED',
                published_at = CURRENT_TIMESTAMP,
                last_error = NULL
            WHERE id = :event_id
            """
        )

        await self.db.execute(
            query,
            {"event_id": event_id},
        )

    async def mark_failed(
        self,
        *,
        event_id: UUID,
        error: str,
    ) -> None:
        query = text(
            """
            UPDATE outbox_events
            SET
                status = 'FAILED',
                attempts = attempts + 1,
                last_error = :error
            WHERE id = :event_id
            """
        )

        await self.db.execute(
            query,
            {
                "event_id": event_id,
                "error": error,
            },
        )