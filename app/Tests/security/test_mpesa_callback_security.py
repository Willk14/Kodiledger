import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import settings
from app.security.mpesa_callback import (
    enforce_mpesa_callback_source,
    enforce_mpesa_callback_token,
)


def _request(peer_ip: str, headers=()) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/webhooks/mpesa",
            "raw_path": b"/api/v1/webhooks/mpesa",
            "query_string": b"",
            "headers": list(headers),
            "client": (peer_ip, 12345),
            "server": ("kodiledger.example", 443),
        }
    )


def test_allowed_safaricom_peer_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "MPESA_CALLBACK_ALLOWED_IPS",
        "196.201.214.200,10.0.0.0/8",
    )

    enforce_mpesa_callback_source(_request("196.201.214.200"))


def test_forwarded_ip_header_cannot_override_untrusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "MPESA_CALLBACK_ALLOWED_IPS",
        "196.201.214.200",
    )

    request = _request(
        "203.0.113.10",
        ((b"x-forwarded-for", b"196.201.214.200"),),
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_mpesa_callback_source(request)

    assert exc_info.value.status_code == 403


def test_local_development_environment_skips_source_filter(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "MPESA_CALLBACK_ALLOWED_IPS", "not-an-ip")

    enforce_mpesa_callback_source(_request("127.0.0.1"))


def test_invalid_allowlist_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MPESA_CALLBACK_ALLOWED_IPS", "not-an-ip")

    with pytest.raises(HTTPException) as exc_info:
        enforce_mpesa_callback_source(_request("196.201.214.200"))

    assert exc_info.value.status_code == 503


def test_callback_token_is_required_and_compared_in_constant_time_path(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "MPESA_CALLBACK_TOKEN",
        "long-random-test-token-value-at-least-32-chars",
    )
    request = _request("196.201.214.200")
    request.scope["query_string"] = (
        b"token=long-random-test-token-value-at-least-32-chars"
    )

    enforce_mpesa_callback_token(request)


def test_invalid_or_missing_callback_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        settings,
        "MPESA_CALLBACK_TOKEN",
        "long-random-test-token-value-at-least-32-chars",
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_mpesa_callback_token(_request("196.201.214.200"))

    assert exc_info.value.status_code == 403


def test_production_without_callback_token_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MPESA_CALLBACK_TOKEN", "")

    with pytest.raises(HTTPException) as exc_info:
        enforce_mpesa_callback_token(_request("196.201.214.200"))

    assert exc_info.value.status_code == 503
