from __future__ import annotations

import json
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import settings
from app.services.event_publisher import EventPublisher


class KafkaEventPublisher(EventPublisher):
    def __init__(
        self,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
    ) -> None:
        self.bootstrap_servers = (
            bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        )
        self.topic = topic or settings.KAFKA_PAYMENT_TOPIC

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            enable_idempotence=True,
        )

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, event: dict[str, Any]) -> None:
        payload = json.dumps(
            event,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")

        await self._producer.send_and_wait(
            self.topic,
            value=payload,
        )
