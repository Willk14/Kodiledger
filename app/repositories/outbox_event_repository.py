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
                created_at,
                locked_at
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
                created_at,
                locked_at
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

    async def claim_pending(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = text(
            """
            WITH candidates AS (
                SELECT id
                FROM outbox_events
                WHERE status = 'PENDING'
                  AND available_at <= CURRENT_TIMESTAMP
                  AND (
                      locked_at IS NULL
                      OR locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                  )
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
            )
            UPDATE outbox_events AS events
            SET locked_at = CURRENT_TIMESTAMP
            FROM candidates
            WHERE events.id = candidates.id
            RETURNING
                events.id,
                events.event_type,
                events.aggregate_type,
                events.aggregate_id,
                events.idempotency_key,
                events.payload,
                events.status,
                events.attempts,
                events.available_at,
                events.published_at,
                events.last_error,
                events.created_at,
                events.locked_at
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
                last_error = NULL,
                locked_at = NULL
            WHERE id = :event_id
            """
        )

        await self.db.execute(
            query,
            {"event_id": event_id},
        )

    async def schedule_retry(
        self,
        *,
        event_id: UUID,
        error: str,
        delay_seconds: int,
    ) -> None:
        query = text(
            """
            UPDATE outbox_events
            SET
                status = 'PENDING',
                attempts = attempts + 1,
                available_at = CURRENT_TIMESTAMP
                    + (:delay_seconds * INTERVAL '1 second'),
                last_error = :error,
                locked_at = NULL
            WHERE id = :event_id
            """
        )

        await self.db.execute(
            query,
            {
                "event_id": event_id,
                "error": error,
                "delay_seconds": delay_seconds,
            },
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
                last_error = :error,
                locked_at = NULL
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
