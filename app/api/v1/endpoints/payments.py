from __future__ import annotations

import logging
import traceback
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.rate_limiter import enforce_stk_push_rate_limit
from app.schemas.mpesa import StkPushRequest, StkPushResponse
from app.services.payment_initiation_service import payment_initiation_service


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


def _build_stk_push_response(
    response: Mapping[str, Any],
) -> StkPushResponse:
    """
    Convert the M-Pesa service response into the public API response.
    """

    return StkPushResponse(
        MerchantRequestID=str(
            response.get("MerchantRequestID", "")
        ),
        CheckoutRequestID=str(
            response.get("CheckoutRequestID", "")
        ),
        ResponseCode=str(
            response.get("ResponseCode", "")
        ),
        ResponseDescription=str(
            response.get("ResponseDescription", "")
        ),
        CustomerMessage=str(
            response.get("CustomerMessage", "")
        ),
    )


@router.post(
    "/stk-push",
    response_model=StkPushResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate M-Pesa STK Push",
)
async def initiate_stk_push(
    request: StkPushRequest,
    _: None = Depends(enforce_stk_push_rate_limit),
) -> StkPushResponse:
    """
    Initiate an M-Pesa STK Push.

    This endpoint only starts the M-Pesa payment request.

    It does not create a ledger entry.
    Ledger processing happens after the M-Pesa callback
    is received and successfully reconciled.
    """

    try:
        response = await payment_initiation_service.initiate_mpesa_stk_push(
            phone_number=request.phone_number,
            amount=request.amount,
            account_reference="KodiLedger",
            transaction_description="KodiLedger Payment",
        )

        if not isinstance(response, Mapping):
            logger.error(
                "M-Pesa service returned unexpected response type: %s",
                type(response).__name__,
            )

            raise RuntimeError(
                "M-Pesa service returned an invalid response."
            )

        logger.info(
            "M-Pesa STK Push initiated successfully "
            "(response_code=%s)",
            response.get("ResponseCode"),
        )

        return _build_stk_push_response(response)

    except ValueError as exc:
        logger.warning(
            "Invalid STK Push request: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        logger.error(
            "M-Pesa STK Push upstream/service failure: %s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Temporary diagnostic logging while we locate the 500.
        print(
            "\n" + "=" * 80,
            flush=True,
        )
        print(
            "STK PUSH EXCEPTION",
            flush=True,
        )
        print(
            f"TYPE: {type(exc).__name__}",
            flush=True,
        )
        print(
            f"MESSAGE: {exc}",
            flush=True,
        )
        print(
            "TRACEBACK:",
            flush=True,
        )
        traceback.print_exc()
        print(
            "=" * 80 + "\n",
            flush=True,
        )

        logger.exception(
            "Unexpected STK Push initiation failure"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate M-Pesa STK Push.",
        ) from exc
