from __future__ import annotations

from uuid import uuid4

import pytest
import redis.asyncio as redis

from app.core.config import settings
from app.core.rate_limiter import RedisRateLimiter


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_limit() -> None:
    client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )

    limiter = RedisRateLimiter(
        client,
        prefix=f"kodiledger:test-rate-limit:{uuid4()}",
    )

    identifier = f"test-client-{uuid4()}"

    try:
        first = await limiter.check(
            identifier,
            limit=2,
            window_seconds=60,
        )

        second = await limiter.check(
            identifier,
            limit=2,
            window_seconds=60,
        )

        third = await limiter.check(
            identifier,
            limit=2,
            window_seconds=60,
        )

        assert first.allowed is True
        assert first.remaining == 1

        assert second.allowed is True
        assert second.remaining == 0

        assert third.allowed is False
        assert third.remaining == 0
        assert third.retry_after > 0

    finally:
        await client.delete(
            f"{limiter.prefix}:{identifier}"
        )
        await client.aclose()
