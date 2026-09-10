import base64
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings


class MpesaService:
    """
    Service responsible for communicating with Safaricom Daraja APIs.

    Responsibilities:
    - Generate Daraja OAuth access tokens
    - Generate STK Push passwords
    - Initiate STK Push requests

    This service does NOT write to the database.
    Payment confirmation is handled by the M-Pesa webhook.
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

    def _validate_phone_number(self, phone_number: str) -> None:
        """Validate Kenyan phone number format used by Daraja."""

        if not phone_number.startswith("254"):
            raise ValueError(
                "Phone number must start with 254."
            )

        if len(phone_number) != 12:
            raise ValueError(
                "Phone number must contain exactly 12 digits."
            )

        if not phone_number.isdigit():
            raise ValueError(
                "Phone number must contain digits only."
            )

    def _validate_amount(self, amount: int) -> None:
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
    # OAuth
    # ------------------------------------------------------------------

    async def get_access_token(self) -> str:
        """
        Request an OAuth access token from Daraja.
        """

        self._validate_credentials()

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

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.get(
                url,
                headers=headers,
            )

        if response.status_code != 200:
            raise RuntimeError(
                "Daraja OAuth request failed: "
                f"HTTP {response.status_code} - "
                f"{response.text}"
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
                "Daraja OAuth response did not contain an access token."
            )

        return str(access_token)

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
        """
        Generate the Base64 encoded Daraja STK Push password.
        """

        raw_password = (
            f"{self.shortcode}"
            f"{self.passkey}"
            f"{timestamp}"
        )

        return base64.b64encode(
            raw_password.encode("utf-8")
        ).decode("utf-8")

    # ------------------------------------------------------------------
    # STK Push
    # ------------------------------------------------------------------

    async def initiate_stk_push(
        self,
        phone_number: str,
        amount: int,
        account_reference: str = "KodiLedger",
        transaction_description: str = "KodiLedger Payment",
    ) -> dict[str, Any]:
        """
        Initiate an M-Pesa STK Push.

        Important:
        This function only starts the payment request.
        It does NOT mark the payment as completed.

        Payment completion happens later through the M-Pesa
        callback/webhook.
        """

        self._validate_credentials()
        self._validate_phone_number(phone_number)
        self._validate_amount(amount)
        self._validate_callback_url()

        # Get OAuth token.
        access_token = await self.get_access_token()

        # Generate Daraja timestamp/password.
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

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

        if response.status_code not in (200, 201):
            raise RuntimeError(
                "Daraja STK Push request failed: "
                f"HTTP {response.status_code} - "
                f"{response.text}"
            )

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Daraja STK Push returned invalid JSON."
            ) from exc

        return data


# ----------------------------------------------------------------------
# Shared service instance
# ----------------------------------------------------------------------

mpesa_service = MpesaService()