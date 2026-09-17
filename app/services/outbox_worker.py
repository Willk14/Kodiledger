from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.outbox_event_repository import OutboxEventRepository
from app.services.event_publisher import EventPublisher


class OutboxWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: EventPublisher,
        *,
        batch_size: int = 100,
        max_attempts: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.publisher = publisher
        self.batch_size = batch_size
        self.max_attempts = max_attempts

    async def run_once(self) -> int:
        async with self.session_factory() as db:
            repository = OutboxEventRepository(db)

            events = await repository.claim_pending(
                limit=self.batch_size,
            )

            await db.commit()

        processed = 0

        for event in events:
            try:
                await self.publisher.publish(event)

                async with self.session_factory() as db:
                    repository = OutboxEventRepository(db)

                    await repository.mark_published(
                        event_id=event["id"],
                    )

                    await db.commit()

                processed += 1

            except Exception as exc:
                next_attempt = event["attempts"] + 1

                async with self.session_factory() as db:
                    repository = OutboxEventRepository(db)

                    if next_attempt >= self.max_attempts:
                        await repository.mark_failed(
                            event_id=event["id"],
                            error=str(exc),
                        )
                    else:
                        delay_seconds = self._retry_delay(
                            next_attempt,
                        )

                        await repository.schedule_retry(
                            event_id=event["id"],
                            error=str(exc),
                            delay_seconds=delay_seconds,
                        )

                    await db.commit()

        return processed

    @staticmethod
    def _retry_delay(attempt: int) -> int:
        return min(5 * (2 ** (attempt - 1)), 300)
