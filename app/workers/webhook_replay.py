from __future__ import annotations

import asyncio
import logging

from app.core.database import SystemSessionLocal
from app.services.webhook_replay_worker import WebhookReplayWorker


POLL_INTERVAL_SECONDS = 5
logger = logging.getLogger(__name__)


async def run_forever() -> None:
    worker = WebhookReplayWorker(SystemSessionLocal)
    logger.info("Webhook replay worker started")
    while True:
        try:
            count = await worker.run_once()
            if count:
                logger.info("Webhook replay worker processed %s callback(s)", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Webhook replay iteration failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        logger.info("Webhook replay worker stopped")


if __name__ == "__main__":
    main()
