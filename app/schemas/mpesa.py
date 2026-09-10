from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# M-PESA STK CALLBACK SCHEMAS
# ============================================================

class ItemKV(BaseModel):
    """Single Name/Value item from M-Pesa CallbackMetadata."""

    model_config = ConfigDict(extra="ignore")

    Name: str
    Value: Any | None = None


class StkCallbackMetadata(BaseModel):
    """Metadata returned by a successful M-Pesa STK transaction."""

    model_config = ConfigDict(extra="ignore")

    Item: list[ItemKV]


class StkCallback(BaseModel):
    """M-Pesa STK Push callback."""

    model_config = ConfigDict(extra="ignore")

    MerchantRequestID: str
    CheckoutRequestID: str
    ResultCode: int
    ResultDesc: str

    # Actual JSON field remains "CallbackMetadata"
    CallbackMetadata: StkCallbackMetadata | None = None


class Body(BaseModel):
    """M-Pesa callback body."""

    model_config = ConfigDict(extra="ignore")

    stkCallback: StkCallback


class MpesaStkPushCallbackPayload(BaseModel):
    """Complete M-Pesa STK callback payload."""

    model_config = ConfigDict(extra="ignore")

    Body: Body


# ============================================================
# STK PUSH REQUEST
# ============================================================

class StkPushRequest(BaseModel):
    """
    Request received by KodiLedger when initiating
    an STK Push.
    """

    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(
        min_length=12,
        max_length=12,
        pattern=r"^254\d{9}$",
        description="Safaricom number in 254XXXXXXXXX format",
        examples=["254798765432"],
    )

    amount: int = Field(
        gt=0,
        description="Amount in Kenyan Shillings",
        examples=[150],
    )


# ============================================================
# STK PUSH RESPONSE
# ============================================================

class StkPushResponse(BaseModel):
    """
    Response returned by Safaricom after an STK Push
    initiation request.
    """

    model_config = ConfigDict(extra="ignore")

    MerchantRequestID: str | None = None
    CheckoutRequestID: str | None = None
    ResponseCode: str | None = None
    ResponseDescription: str | None = None
    CustomerMessage: str | None = None


# ============================================================
# INTERNAL NORMALIZED RESPONSE
# ============================================================

class StkPushResult(BaseModel):
    """
    Normalized internal result used by KodiLedger.
    """

    success: bool

    merchant_request_id: str | None = None
    checkout_request_id: str | None = None

    response_code: str | None = None
    response_description: str | None = None
    customer_message: str | None = None