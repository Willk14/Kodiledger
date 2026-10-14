import asyncio
import httpx


URL = "http://127.0.0.1:8000/api/v1/webhooks/mpesa"


payload = {
    "Body": {
        "stkCallback": {
            "MerchantRequestID": "OUTBOX-MERCHANT-001",
            "CheckoutRequestID": "OUTBOX-CHECKOUT-001",
            "ResultCode": 0,
            "ResultDesc": "The service request is processed successfully.",
            "CallbackMetadata": {
                "Item": [
                    {"Name": "Amount", "Value": 1000},
                    {
                        "Name": "MpesaReceiptNumber",
                        "Value": "OUTBOX-TEST-001",
                    },
                    {
                        "Name": "TransactionDate",
                        "Value": 20260913120000,
                    },
                    {
                        "Name": "PhoneNumber",
                        "Value": 254798765432,
                    },
                ]
            },
        }
    }
}


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            URL,
            json=payload,
        )

        print("STATUS:", response.status_code)
        print("RESPONSE:", response.json())


if __name__ == "__main__":
    asyncio.run(main())