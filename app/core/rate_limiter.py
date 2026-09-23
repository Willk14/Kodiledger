from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis
from fastapi import HTTPException, Request, status

from app.core.config import settings


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RedisRateLimiter:
    """
    Redis-backed fixed-window rate limiter.

    The increment + expiry operation is performed atomically
    inside Redis using Lua so concurrent requests cannot race
    between INCR and EXPIRE.
    """

    _SCRIPT = """
    local current = redis.call("INCR", KEYS[1])

    if current == 1 then
        redis.call("EXPIRE", KEYS[1], ARGV[1])
    end

    local ttl = redis.call("TTL", KEYS[1])

    return {current, ttl}
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        prefix: str = "kodiledger:rate-limit",
    ) -> None:
        self.client = client
        self.prefix = prefix

    async def check(
        self,
        identifier: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        key = f"{self.prefix}:{identifier}"

        try:
            result = await self.client.eval(
                self._SCRIPT,
                1,
                key,
                window_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                "Rate limiter Redis operation failed."
            ) from exc

        current = int(result[0])
        ttl = max(int(result[1]), 0)

        remaining = max(limit - current, 0)
        allowed = current <= limit

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            retry_after=ttl,
        )


redis_client = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
)

rate_limiter = RedisRateLimiter(redis_client)


async def enforce_stk_push_rate_limit(
    request: Request,
) -> None:
    """
    Apply a per-IP rate limit to STK Push initiation requests.
    """

    client_ip = (
        request.client.host
        if request.client is not None
        else "unknown"
    )

    result = await rate_limiter.check(
        client_ip,
        limit=settings.RATE_LIMIT_STK_PUSH_REQUESTS,
        window_seconds=settings.RATE_LIMIT_STK_PUSH_WINDOW_SECONDS,
    )

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="STK Push rate limit exceeded. Try again later.",
            headers={
                "Retry-After": str(result.retry_after),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
            },
        )
