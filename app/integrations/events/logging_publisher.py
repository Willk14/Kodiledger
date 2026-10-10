from __future__ import annotations

import logging
from typing import Any

from app.services.event_publisher import EventPublisher


logger = logging.getLogger(__name__)


class LoggingEventPublisher(EventPublisher):
    """Development publisher used to verify the worker independently."""

    async def publish(self, event: dict[str, Any]) -> None:
        logger.info(
            "Published outbox event: id=%s type=%s aggregate_type=%s aggregate_id=%s",
            event["id"],
            event["event_type"],
            event["aggregate_type"],
            event["aggregate_id"],
        )
