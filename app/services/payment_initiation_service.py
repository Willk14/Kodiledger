from typing import Any

from app.integrations.mpesa.client import MpesaClient, mpesa_client


class PaymentInitiationService:
    """
    Application service responsible for initiating payments.

    The service coordinates payment initiation but does not
    implement Daraja's HTTP/OAuth protocol itself.
    """

    def __init__(self, mpesa_client: MpesaClient) -> None:
        self.mpesa_client = mpesa_client

    async def initiate_mpesa_stk_push(
        self,
        phone_number: str,
        amount: int,
        account_reference: str = "KodiLedger",
        transaction_description: str = "KodiLedger Payment",
    ) -> dict[str, Any]:
        return await self.mpesa_client.initiate_stk_push(
            phone_number=phone_number,
            amount=amount,
            account_reference=account_reference,
            transaction_description=transaction_description,
        )

    async def query_mpesa_stk_push(
        self, checkout_request_id: str
    ) -> dict[str, Any]:
        return await self.mpesa_client.query_stk_push(checkout_request_id)


payment_initiation_service = PaymentInitiationService(mpesa_client)
