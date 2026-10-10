from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import redis.asyncio as redis
from fastapi import FastAPI

import app.api.v1.endpoints.payments as payments_module
from app.core.config import settings
from app.core.rate_limiter import rate_limiter


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stk_push_rate_limit_blocks_sixth_request(
    monkeypatch,
) -> None:
    test_app = FastAPI()

    test_app.include_router(
        payments_module.router,
        prefix="/api/v1",
    )

    mock_stk_push = AsyncMock(
        return_value={
            "MerchantRequestID": "TEST-MERCHANT",
            "CheckoutRequestID": "TEST-CHECKOUT",
            "ResponseCode": "0",
            "ResponseDescription": "Success",
            "CustomerMessage": "Success",
        }
    )

    monkeypatch.setattr(
        payments_module.payment_initiation_service,
        "initiate_mpesa_stk_push",
        mock_stk_push,
    )

    redis_client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )

    client_ip = "127.0.0.1"

    rate_limit_key = (
        f"{rate_limiter.prefix}:{client_ip}"
    )

    await redis_client.delete(rate_limit_key)

    try:
        transport = httpx.ASGITransport(
            app=test_app,
        )

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as http_client:

            responses = []

            for _ in range(6):
                response = await http_client.post(
                    "/api/v1/payments/stk-push",
                    json={
                        "phone_number": "254798765432",
                        "amount": 150,
                    },
                )

                responses.append(response)

            for response in responses[:5]:
                assert response.status_code == 200

            sixth = responses[5]

            assert sixth.status_code == 429

            assert (
                sixth.json()["detail"]
                == "STK Push rate limit exceeded. "
                "Try again later."
            )

            assert (
                sixth.headers["X-RateLimit-Limit"]
                == "5"
            )

            assert (
                sixth.headers["X-RateLimit-Remaining"]
                == "0"
            )

            assert int(
                sixth.headers["Retry-After"]
            ) > 0

            assert mock_stk_push.await_count == 5

    finally:
        await redis_client.delete(rate_limit_key)
        await redis_client.aclose()
