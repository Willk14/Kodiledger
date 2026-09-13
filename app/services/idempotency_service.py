import asyncio
import secrets

import redis.asyncio as aioredis

from app.core.config import settings


IDEMPOTENCY_TTL_SECONDS = 86400


class IdempotencyService:
    """
    Redis-based fast-path idempotency service.

    Redis prevents unnecessary duplicate processing attempts.

    PostgreSQL remains the authoritative idempotency mechanism.
    """

    def __init__(self) -> None:
        self.redis_url = settings.REDIS_URL
        self.ttl_seconds = IDEMPOTENCY_TTL_SECONDS

    async def acquire(
        self,
        receipt: str,
    ) -> tuple[bool, str]:
        """
        Attempt to acquire an idempotency lock for a payment receipt.

        Returns:
            (True, token)  -> lock acquired
            (False, token) -> lock already exists

        If Redis is unavailable, the operation fails open and
        PostgreSQL is allowed to provide authoritative protection.
        """

        token = secrets.token_urlsafe(16)
        redis_client = None

        try:
            redis_client = aioredis.from_url(
                self.redis_url,
                socket_timeout=1.0,
            )

            acquired = await asyncio.wait_for(
                redis_client.set(
                    f"mpesa_lock:{receipt}",
                    token,
                    nx=True,
                    ex=self.ttl_seconds,
                ),
                timeout=1.0,
            )

            return bool(acquired), token

        except Exception as exc:
            print(
                f"Redis warning: bypassing fast-path lock: {exc}"
            )

            # PostgreSQL remains authoritative.
            return True, token

        finally:
            if redis_client is not None:
                try:
                    await redis_client.aclose()
                except Exception:
                    pass

    async def release(
        self,
        receipt: str,
        token: str,
    ) -> None:
        """
        Release the Redis lock only if it belongs to this request.
        """

        redis_client = None

        script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        end
        return 0
        """

        try:
            redis_client = aioredis.from_url(
                self.redis_url,
                socket_timeout=1.0,
            )

            await asyncio.wait_for(
                redis_client.eval(
                    script,
                    1,
                    f"mpesa_lock:{receipt}",
                    token,
                ),
                timeout=1.0,
            )

        except Exception as exc:
            print(
                f"Redis cleanup warning: {exc}"
            )

        finally:
            if redis_client is not None:
                try:
                    await redis_client.aclose()
                except Exception:
                    pass


