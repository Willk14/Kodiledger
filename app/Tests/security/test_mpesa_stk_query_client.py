from __future__ import annotations

import json

import httpx
import pytest
from unittest.mock import AsyncMock

from app.integrations.mpesa.client import MpesaClient
from app.core.config import settings


@pytest.mark.asyncio
async def test_stk_query_sends_checkout_id_and_generated_password():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "ResponseCode": "0",
                "ResultCode": "0",
                "ResultDesc": "The service request is processed successfully.",
            },
        )

    client = MpesaClient()
    client.consumer_key = "test-key"
    client.consumer_secret = "test-secret"
    client.passkey = "test-passkey"
    client.shortcode = "174379"
    client.base_url = "https://sandbox.safaricom.co.ke"
    client.generate_timestamp = lambda: "20260102123456"
    client.get_access_token = AsyncMock(return_value="test-access-token")
    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )

    try:
        response = await client.query_stk_push("ws_CO_TEST_001")
    finally:
        await client.close()

    assert captured["url"] == (
        "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"
    )
    assert captured["authorization"] == "Bearer test-access-token"
    request_body = captured["body"]
    assert request_body["BusinessShortCode"] == "174379"
    assert request_body["Timestamp"] == "20260102123456"
    assert request_body["CheckoutRequestID"] == "ws_CO_TEST_001"
    assert request_body["Password"] == client.generate_password("20260102123456")
    assert response["ResultCode"] == "0"


@pytest.mark.asyncio
async def test_stk_query_rejects_provider_http_error_without_echoing_body():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="secret provider response")

    client = MpesaClient()
    client.consumer_key = "test-key"
    client.consumer_secret = "test-secret"
    client.passkey = "test-passkey"
    client.shortcode = "174379"
    client.base_url = "https://sandbox.safaricom.co.ke"
    client.get_access_token = AsyncMock(return_value="test-access-token")
    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )

    try:
        with pytest.raises(RuntimeError) as error:
            await client.query_stk_push("ws_CO_TEST_001")
    finally:
        await client.close()

    assert "HTTP 500" in str(error.value)
    assert "secret provider response" not in str(error.value)


def test_callback_url_adds_token_and_preserves_other_query_parameters(monkeypatch):
    monkeypatch.setattr(
        settings,
        "MPESA_CALLBACK_TOKEN",
        "callback-secret-value-with-at-least-32-chars",
    )
    client = MpesaClient()
    client.callback_url = "https://example.test/hooks/mpesa?source=daraja&token=old"

    url = client._callback_url_with_token()

    assert url == (
        "https://example.test/hooks/mpesa?source=daraja&token=callback-secret-value-with-at-least-32-chars"
    )


def test_production_stk_initiation_requires_callback_token(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MPESA_CALLBACK_TOKEN", "")
    client = MpesaClient()
    client.callback_url = "https://example.test/hooks/mpesa"

    with pytest.raises(RuntimeError, match="MPESA_CALLBACK_TOKEN must contain"):
        client._validate_callback_url()


def test_production_stk_initiation_requires_https_callback_url(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "MPESA_CALLBACK_TOKEN",
        "callback-secret-value-with-at-least-32-chars",
    )
    client = MpesaClient()
    client.callback_url = "http://example.test/hooks/mpesa"

    with pytest.raises(RuntimeError, match="must use HTTPS"):
        client._validate_callback_url()
