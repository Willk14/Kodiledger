from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: dict[str, Any]) -> None:
        """Publish one outbox event."""
        raise NotImplementedError
