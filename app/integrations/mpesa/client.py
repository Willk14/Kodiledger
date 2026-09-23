from __future__ import annotations

import asyncio
import base64
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
import logging

logger = logging.getLogger("kodiledger.mpesa")
logger.setLevel(logging.INFO)
logger.propagate = True



class MpesaClient:
    """
    Low-level client for Safaricom Daraja APIs.

    Responsibilities:
    - Validate Daraja configuration and STK Push inputs
    - Generate OAuth access tokens
    - Cache OAuth access tokens in-process
    - Reuse a shared HTTP client
    - Generate STK Push timestamp/password
    - Submit STK Push requests

    This class does not access the database.
    """

    def __init__(self) -> None:
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.passkey = settings.MPESA_PASSKEY
        self.shortcode = str(settings.MPESA_SHORTCODE)

        self.base_url = getattr(
            settings,
            "MPESA_BASE_URL",
            "https://sandbox.safaricom.co.ke",
        )

        self.callback_url = getattr(
            settings,
            "MPESA_CALLBACK_URL",
            "",
        )

        self.timeout = httpx.Timeout(
            connect=5.0,
            read=15.0,
            write=10.0,
            pool=5.0,
        )

        # --------------------------------------------------------------
        # HTTP client reuse
        # --------------------------------------------------------------
        self._http_client: httpx.AsyncClient | None = None

        # --------------------------------------------------------------
        # OAuth token cache
        # --------------------------------------------------------------
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

        # Prevent concurrent requests from refreshing the token at once.
        self._token_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Return a shared AsyncClient so TCP/TLS connections can be reused."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
            )

        return self._http_client

    async def close(self) -> None:
        """Close the shared HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_credentials(self) -> None:
        """Ensure required Daraja credentials are configured."""
        if not self.consumer_key:
            raise RuntimeError("MPESA_CONSUMER_KEY is not configured.")

        if not self.consumer_secret:
            raise RuntimeError("MPESA_CONSUMER_SECRET is not configured.")

        if not self.passkey:
            raise RuntimeError("MPESA_PASSKEY is not configured.")

        if not self.shortcode:
            raise RuntimeError("MPESA_SHORTCODE is not configured.")

    @staticmethod
    def _validate_phone_number(phone_number: str) -> None:
        """Validate Kenyan phone number format used by Daraja."""
        if not phone_number.startswith("254"):
            raise ValueError("Phone number must start with 254.")

        if len(phone_number) != 12:
            raise ValueError(
                "Phone number must contain exactly 12 digits."
            )

        if not phone_number.isdigit():
            raise ValueError(
                "Phone number must contain digits only."
            )

    @staticmethod
    def _validate_amount(amount: int) -> None:
        """Validate STK Push amount."""
        if amount <= 0:
            raise ValueError(
                "STK Push amount must be greater than zero."
            )

    def _validate_callback_url(self) -> None:
        """Ensure a callback URL has been configured."""
        if not self.callback_url:
            raise RuntimeError(
                "MPESA_CALLBACK_URL is not configured."
            )

    # ------------------------------------------------------------------
    # OAuth cache
    # ------------------------------------------------------------------

    def _has_valid_cached_token(self) -> bool:
        """Return True when the cached OAuth token is still valid."""
        return (
            self._access_token is not None
            and time.monotonic() < self._access_token_expires_at
        )

    async def get_access_token(
        self,
        *,
        force_refresh: bool = False,
    ) -> str:
        """
        Return a valid Daraja OAuth token.

        Uses an in-process cache to avoid requesting a new OAuth token
        on every STK Push request.
        """
        self._validate_credentials()

        if not force_refresh and self._has_valid_cached_token():
            logger.info("Using cached Daraja OAuth token.")
            return self._access_token  # type: ignore[return-value]

        async with self._token_lock:
            # Another request may have refreshed the token while this
            # request was waiting for the lock.
            if not force_refresh and self._has_valid_cached_token():
                logger.info(
                    "Using cached Daraja OAuth token after waiting for token lock."
                )
                return self._access_token  # type: ignore[return-value]

            credentials = (
                f"{self.consumer_key}:{self.consumer_secret}"
            )

            encoded_credentials = base64.b64encode(
                credentials.encode("utf-8")
            ).decode("utf-8")

            url = (
                f"{self.base_url}"
                "/oauth/v1/generate"
                "?grant_type=client_credentials"
            )

            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/json",
            }

            client = await self._get_http_client()

            start = time.perf_counter()

            try:
                response = await client.get(
                    url,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                elapsed = time.perf_counter() - start

                logger.error(
                    "Daraja OAuth HTTP request failed after %.3fs: %s",
                    elapsed,
                    exc,
                )

                raise RuntimeError(
                    "Unable to communicate with Daraja OAuth endpoint."
                ) from exc

            elapsed = time.perf_counter() - start

            logger.info(
                "Daraja OAuth request completed in %.3fs (HTTP %s).",
                elapsed,
                response.status_code,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    "Daraja OAuth request failed: "
                    f"HTTP {response.status_code}"
                )

            try:
                data: dict[str, Any] = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    "Daraja OAuth returned invalid JSON."
                ) from exc

            access_token = data.get("access_token")

            if not access_token:
                raise RuntimeError(
                    "Daraja OAuth response did not contain "
                    "an access token."
                )

            expires_in_raw = data.get("expires_in", 3600)

            try:
                expires_in = int(expires_in_raw)
            except (TypeError, ValueError):
                expires_in = 3600

            # Refresh before actual expiration.
            cache_seconds = max(expires_in - 60, 1)

            self._access_token = str(access_token)
            self._access_token_expires_at = (
                time.monotonic() + cache_seconds
            )

            logger.info(
                "Daraja OAuth token cached for %d seconds.",
                cache_seconds,
            )

            return self._access_token

    # ------------------------------------------------------------------
    # STK Push helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_timestamp() -> str:
        """
        Generate the timestamp required by Daraja.

        Format:
        YYYYMMDDHHMMSS
        """
        return datetime.now(timezone.utc).strftime(
            "%Y%m%d%H%M%S"
        )

    def generate_password(self, timestamp: str) -> str:
        """Generate the Base64 encoded Daraja STK Push password."""
        raw_password = (
            f"{self.shortcode}"
            f"{self.passkey}"
            f"{timestamp}"
        )

        return base64.b64encode(
            raw_password.encode("utf-8")
        ).decode("utf-8")

    async def initiate_stk_push(
        self,
        phone_number: str,
        amount: int,
        account_reference: str = "KodiLedger",
        transaction_description: str = "KodiLedger Payment",
    ) -> dict[str, Any]:
        import time

        total_start = time.perf_counter()

        print(
            "MPESA TEST: initiate_stk_push reached",
            flush=True,
        )

        self._validate_credentials()
        self._validate_phone_number(phone_number)
        self._validate_amount(amount)
        self._validate_callback_url()

        oauth_start = time.perf_counter()
        access_token = await self.get_access_token()
        oauth_elapsed = time.perf_counter() - oauth_start

        print(
            f"TIMING: Daraja OAuth completed in {oauth_elapsed:.3f}s",
            flush=True,
        )

        timestamp = self.generate_timestamp()
        password = self.generate_password(timestamp)

        url = (
            f"{self.base_url}"
            "/mpesa/stkpush/v1/processrequest"
        )

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone_number,
            "PartyB": self.shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference,
            "TransactionDesc": transaction_description,
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        client = await self._get_http_client()

        stk_start = time.perf_counter()

        try:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            stk_elapsed = time.perf_counter() - stk_start
            total_elapsed = time.perf_counter() - total_start

            print(
                f"TIMING: Daraja STK Push HTTP request failed "
                f"after {stk_elapsed:.3f}s",
                flush=True,
            )
            print(
                f"TIMING: Total STK Push initiation failed "
                f"after {total_elapsed:.3f}s",
                flush=True,
            )

            raise RuntimeError(
                f"Daraja STK Push HTTP request failed: {exc}"
            ) from exc

        stk_elapsed = time.perf_counter() - stk_start

        print(
            f"TIMING: Daraja STK Push request completed in "
            f"{stk_elapsed:.3f}s "
            f"(HTTP {response.status_code})",
            flush=True,
        )

        if response.status_code not in (200, 201):
            total_elapsed = time.perf_counter() - total_start

            print(
                f"TIMING: Total STK Push initiation failed "
                f"after {total_elapsed:.3f}s",
                flush=True,
            )

            raise RuntimeError(
                "Daraja STK Push request failed: "
                f"HTTP {response.status_code} - "
                f"{response.text}"
            )

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            total_elapsed = time.perf_counter() - total_start

            print(
                f"TIMING: Total STK Push initiation failed "
                f"after {total_elapsed:.3f}s",
                flush=True,
            )

            raise RuntimeError(
                "Daraja STK Push returned invalid JSON."
            ) from exc

        total_elapsed = time.perf_counter() - total_start

        print(
            f"TIMING: Total STK Push initiation completed in "
            f"{total_elapsed:.3f}s",
            flush=True,
        )

        return data




    # ------------------------------------------------------------------
    # STK Push
    # ------------------------------------------------------------------


mpesa_client = MpesaClient()
