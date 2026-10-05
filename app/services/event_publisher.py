from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: dict[str, Any]) -> None:
        """Publish one outbox event."""
        raise NotImplementedError

    async def publish_batch(
        self,
        events: list[dict[str, Any]],
    ) -> list[Exception | None]:
        """Publish events concurrently and return one outcome per event.

        Implementations can override this to use a native bulk API. The default
        preserves the one-event publisher contract while allowing producers
        such as aiokafka to batch concurrent sends internally.
        """

        async def publish_one(event: dict[str, Any]) -> Exception | None:
            try:
                await self.publish(event)
            except Exception as exc:
                return exc
            return None

        return await asyncio.gather(*(publish_one(event) for event in events))
