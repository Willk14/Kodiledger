from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox_event import OutboxEvent


class OutboxEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _to_dict(event: OutboxEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "idempotency_key": event.idempotency_key,
            "payload": event.payload,
            "status": event.status,
            "attempts": event.attempts,
            "available_at": event.available_at,
            "published_at": event.published_at,
            "last_error": event.last_error,
            "created_at": event.created_at,
            "locked_at": event.locked_at,
        }

    async def create(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        stmt = (
            insert(OutboxEvent)
            .values(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            .on_conflict_do_nothing(
                index_elements=[OutboxEvent.idempotency_key],
            )
            .returning(OutboxEvent)
        )

        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()

        if event is not None:
            return self._to_dict(event)

        existing = await self.db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.idempotency_key == idempotency_key,
            )
        )

        if existing is None:
            raise RuntimeError(
                "Outbox event could not be inserted or retrieved"
            )

        return self._to_dict(existing)

    async def claim_pending(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        candidates = (
            await self.db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status == "PENDING",
                    OutboxEvent.available_at <= func.now(),
                    (
                        (OutboxEvent.locked_at.is_(None))
                        | (
                            OutboxEvent.locked_at
                            < func.now() - func.make_interval(0, 0, 0, 0, 0, 5, 0)
                        )
                    ),
                )
                .order_by(OutboxEvent.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()

        if not candidates:
            return []

        event_ids = [event.id for event in candidates]

        result = await self.db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(event_ids))
            .values(locked_at=func.now())
            .returning(OutboxEvent)
        )

        claimed = result.scalars().all()

        return [self._to_dict(event) for event in claimed]

    async def mark_published(
        self,
        *,
        event_id: UUID,
    ) -> None:
        await self.db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status="PUBLISHED",
                published_at=func.now(),
                last_error=None,
                locked_at=None,
            )
        )

    async def schedule_retry(
        self,
        *,
        event_id: UUID,
        error: str,
        delay_seconds: int,
    ) -> None:
        await self.db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status="PENDING",
                attempts=OutboxEvent.attempts + 1,
                available_at=(
                    func.now()
                    + func.make_interval(0, 0, 0, 0, 0, 0, delay_seconds)
                ),
                last_error=error,
                locked_at=None,
            )
        )

    async def mark_failed(
        self,
        *,
        event_id: UUID,
        error: str,
    ) -> None:
        await self.db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status="FAILED",
                attempts=OutboxEvent.attempts + 1,
                last_error=error,
                locked_at=None,
            )
        )


        