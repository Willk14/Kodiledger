from fastapi import APIRouter, HTTPException, status

from app.schemas.mpesa import StkPushRequest, StkPushResponse
from app.services.payment_initiation_service import (
    payment_initiation_service,
)


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


@router.post(
    "/stk-push",
    response_model=StkPushResponse,
    status_code=status.HTTP_200_OK,
)
async def initiate_stk_push(
    request: StkPushRequest,
) -> StkPushResponse:
    """
    Initiate an M-Pesa STK Push.

    This endpoint only starts the payment request.
    It does not create a ledger entry.

    The ledger is updated later when Safaricom sends
    the successful payment callback.
    """

    try:
        response = await payment_initiation_service.initiate_mpesa_stk_push(
            phone_number=request.phone_number,
            amount=request.amount,
            account_reference="KodiLedger",
            transaction_description="KodiLedger Payment",
        )

        return StkPushResponse(
            MerchantRequestID=response.get("MerchantRequestID", ""),
            CheckoutRequestID=response.get("CheckoutRequestID", ""),
            ResponseCode=str(response.get("ResponseCode", "")),
            ResponseDescription=response.get(
                "ResponseDescription",
                "",
            ),
            CustomerMessage=response.get(
                "CustomerMessage",
                "",
            ),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate M-Pesa STK Push.",
        ) from exc
