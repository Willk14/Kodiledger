from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.core.config import settings
from app.integrations.events import kafka_publisher
from app.services.event_publisher import EventPublisher
from app.workers import outbox as outbox_worker_module


class SelectivePublisher(EventPublisher):
    def __init__(self, failing_key: str | None = None) -> None:
        self.failing_key = failing_key
        self.published_events: list[dict[str, object]] = []

    async def publish(self, event: dict[str, object]) -> None:
        if event["idempotency_key"] == self.failing_key:
            raise RuntimeError("simulated event failure")
        self.published_events.append(event)


@pytest.mark.asyncio
async def test_publish_batch_keeps_event_identity_and_reports_partial_failure() -> None:
    events = [
        {
            "id": uuid4(),
            "idempotency_key": f"batch-{index}",
            "payload": {"ordinal": index},
        }
        for index in range(3)
    ]
    publisher = SelectivePublisher(failing_key="batch-1")

    outcomes = await publisher.publish_batch(events)

    assert outcomes[0] is None
    assert isinstance(outcomes[1], RuntimeError)
    assert outcomes[2] is None
    assert [event["id"] for event in publisher.published_events] == [
        events[0]["id"],
        events[2]["id"],
    ]
    assert [event["idempotency_key"] for event in publisher.published_events] == [
        "batch-0",
        "batch-2",
    ]
    assert [event["payload"] for event in publisher.published_events] == [
        {"ordinal": 0},
        {"ordinal": 2},
    ]


def test_kafka_publisher_uses_configured_batch_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    producer_args: dict[str, object] = {}

    class FakeProducer:
        def __init__(self, **kwargs: object) -> None:
            producer_args.update(kwargs)

    monkeypatch.setattr(kafka_publisher, "AIOKafkaProducer", FakeProducer)

    kafka_publisher.KafkaEventPublisher()

    assert producer_args["linger_ms"] == settings.OUTBOX_MAX_BATCH_WAIT_MS
    assert producer_args["enable_idempotence"] is True


@pytest.mark.asyncio
async def test_empty_worker_poll_sleeps_for_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    class FakePublisher:
        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class FakeWorker:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def run_once(self) -> int:
            return 0

    async def cancel_at_next_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        outbox_worker_module,
        "KafkaEventPublisher",
        FakePublisher,
    )
    monkeypatch.setattr(outbox_worker_module, "OutboxWorker", FakeWorker)
    monkeypatch.setattr(
        outbox_worker_module.asyncio,
        "sleep",
        cancel_at_next_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await outbox_worker_module.run_forever()

    assert sleeps == [settings.OUTBOX_POLL_INTERVAL_MS / 1000]
