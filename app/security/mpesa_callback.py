from __future__ import annotations

import hmac
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request, status

from app.core.config import settings


def enforce_mpesa_callback_token(request: Request) -> None:
    """Require the shared URL token outside local/test environments."""
    configured_token = settings.MPESA_CALLBACK_TOKEN
    local_environment = settings.ENVIRONMENT.strip().lower() in {
        "development",
        "test",
    }
    if not configured_token:
        if local_environment:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M-Pesa callback token verification is misconfigured.",
        )
    if not local_environment and len(configured_token) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M-Pesa callback token verification is misconfigured.",
        )

    provided_token = request.query_params.get("token", "")
    if not hmac.compare_digest(provided_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="M-Pesa callback token is invalid.",
        )


def enforce_mpesa_callback_source(request: Request) -> None:
    """Enforce Safaricom's callback source allowlist outside local/test use.

    Only the ASGI peer address is considered. Forwarding headers are not
    trusted here because clients can forge them unless a trusted proxy
    overwrites them and the ASGI server is configured to trust that proxy.
    """
    if settings.ENVIRONMENT.strip().lower() in {"development", "test"}:
        return

    client = request.client
    try:
        source_ip = ip_address(client.host) if client is not None else None
        networks = [
            ip_network(value.strip(), strict=False)
            for value in settings.MPESA_CALLBACK_ALLOWED_IPS.split(",")
            if value.strip()
        ]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M-Pesa callback source verification is misconfigured.",
        ) from exc

    if source_ip is None or not any(
        source_ip.version == network.version and source_ip in network
        for network in networks
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="M-Pesa callback source is not allowed.",
        )
