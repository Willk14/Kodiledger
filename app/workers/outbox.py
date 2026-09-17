from __future__ import annotations

import asyncio
import logging

from app.core.database import SystemSessionLocal
from app.integrations.events.logging_publisher import LoggingEventPublisher
from app.services.outbox_worker import OutboxWorker


POLL_INTERVAL_SECONDS = 5
BATCH_SIZE = 100
MAX_ATTEMPTS = 5


logger = logging.getLogger(__name__)


async def run_forever() -> None:
    publisher = LoggingEventPublisher()

    worker = OutboxWorker(
        SystemSessionLocal,
        publisher,
        batch_size=BATCH_SIZE,
        max_attempts=MAX_ATTEMPTS,
    )

    logger.info(
        "Outbox worker started: poll_interval=%ss batch_size=%s max_attempts=%s",
        POLL_INTERVAL_SECONDS,
        BATCH_SIZE,
        MAX_ATTEMPTS,
    )

    while True:
        try:
            processed = await worker.run_once()

            if processed:
                logger.info(
                    "Outbox worker processed %s event(s)",
                    processed,
                )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception("Outbox worker iteration failed")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        logger.info("Outbox worker stopped")


if __name__ == "__main__":
    main()
