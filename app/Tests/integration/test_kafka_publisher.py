from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from aiokafka import AIOKafkaConsumer

from app.core.config import settings
from app.integrations.events.kafka_publisher import KafkaEventPublisher


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kafka_publisher() -> None:
    group_id = f"kafkaledger-test-{uuid.uuid4()}"

    consumer = AIOKafkaConsumer(
        settings.KAFKA_PAYMENT_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        auto_offset_reset="earliest",
    )

    publisher = KafkaEventPublisher()

    await consumer.start()
    await publisher.start()

    payment_id = f"test-payment-{uuid.uuid4()}"

    event = {
        "event_type": "PAYMENT_PROCESSED",
        "payment_transaction_id": payment_id,
        "amount": "1500.00",
    }

    try:
        await publisher.publish(event)

        received = None

        for _ in range(20):
            try:
                message = await asyncio.wait_for(
                    consumer.getone(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            payload = json.loads(message.value.decode("utf-8"))

            if payload.get("payment_transaction_id") == payment_id:
                received = payload
                break

        assert received is not None
        assert received["event_type"] == "PAYMENT_PROCESSED"
        assert received["payment_transaction_id"] == payment_id
        assert received["amount"] == "1500.00"

    finally:
        await publisher.stop()
        await consumer.stop()
