from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.outbox_event_repository import OutboxEventRepository
from app.services.event_publisher import EventPublisher


logger = logging.getLogger(__name__)


class OutboxWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: EventPublisher,
        *,
        batch_size: int = 100,
        max_attempts: int = 5,
        lock_timeout_seconds: int = 300,
    ) -> None:
        self.session_factory = session_factory
        self.publisher = publisher
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.lock_timeout_seconds = lock_timeout_seconds

    async def run_once(self) -> int:
        started_at = perf_counter()
        async with self.session_factory() as db:
            repository = OutboxEventRepository(db)
            events = await repository.claim_pending(
                limit=self.batch_size,
                lock_timeout_seconds=self.lock_timeout_seconds,
            )
            # Release PostgreSQL row locks before any Kafka network I/O.
            await db.commit()

        if not events:
            return 0

        stale_lock_recoveries = sum(
            bool(event.get("_stale_lock_reclaimed")) for event in events
        )
        publish_events = [
            {
                key: value
                for key, value in event.items()
                if key != "_stale_lock_reclaimed"
            }
            for event in events
        ]

        try:
            outcomes = await self.publisher.publish_batch(publish_events)
            if len(outcomes) != len(events) or any(
                outcome is not None and not isinstance(outcome, Exception)
                for outcome in outcomes
            ):
                raise RuntimeError("Publisher returned invalid batch outcomes")
        except Exception as exc:
            # A batch-level error applies to each unreported event. Publishers
            # that can report partial delivery should return per-event results.
            outcomes = [exc] * len(events)

        results = await asyncio.gather(
            *(
                self._record_outcome(event, outcome)
                for event, outcome in zip(events, outcomes, strict=True)
            ),
            return_exceptions=True,
        )

        published = sum(result == "published" for result in results)
        retries = sum(result == "retry" for result in results)
        permanently_failed = sum(result == "failed" for result in results)
        persistence_errors = sum(
            isinstance(result, BaseException) for result in results
        )

        logger.info(
            "Outbox batch complete batch_size=%d published=%d failed=%d "
            "retries=%d permanently_failed=%d stale_lock_recoveries=%d "
            "persistence_errors=%d duration_ms=%.2f",
            len(events),
            published,
            len(events) - published,
            retries,
            permanently_failed,
            stale_lock_recoveries,
            persistence_errors,
            (perf_counter() - started_at) * 1000,
        )
        return published

    async def _record_outcome(
        self,
        event: dict[str, Any],
        publish_error: Exception | None,
    ) -> str:
        try:
            if publish_error is None:
                async with self.session_factory() as db:
                    repository = OutboxEventRepository(db)
                    await repository.mark_published(event_id=event["id"])
                    await db.commit()
                return "published"
        except Exception as exc:
            # A status-write failure after Kafka delivery is retryable; this
            # preserves at-least-once behavior across the publish/commit window.
            publish_error = exc

        assert publish_error is not None
        next_attempt = event["attempts"] + 1

        async with self.session_factory() as db:
            repository = OutboxEventRepository(db)
            if next_attempt >= self.max_attempts:
                await repository.mark_failed(
                    event_id=event["id"],
                    error=str(publish_error),
                )
                outcome = "failed"
            else:
                await repository.schedule_retry(
                    event_id=event["id"],
                    error=str(publish_error),
                    delay_seconds=self._retry_delay(next_attempt),
                )
                outcome = "retry"

            await db.commit()
            return outcome

    @staticmethod
    def _retry_delay(attempt: int) -> int:
        return min(5 * (2 ** (attempt - 1)), 300)
