from __future__ import annotations

from typing import Any

from app.services.event_publisher import EventPublisher


class TestEventPublisher(EventPublisher):
    __test__ = False
    def __init__(self) -> None:
        self.published_events: list[dict[str, Any]] = []
        self.fail = False

    async def publish(self, event: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("Simulated publisher failure")

        self.published_events.append(event)
