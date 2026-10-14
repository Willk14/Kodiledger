import asyncio
import httpx

URL = "http://127.0.0.1:8000/api/v1/webhooks/mpesa"


def payload(receipt: str, merchant: str, checkout: str):
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": merchant,
                "CheckoutRequestID": checkout,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 7000},
                        {"Name": "MpesaReceiptNumber", "Value": receipt},
                        {"Name": "TransactionDate", "Value": 20261001120000},
                        {"Name": "PhoneNumber", "Value": 254798765432},
                    ]
                },
            }
        }
    }


async def send(client: httpx.AsyncClient, receipt: str, merchant: str, checkout: str):
    response = await client.post(
        URL,
        json=payload(receipt, merchant, checkout),
    )

    print(f"{receipt}: {response.status_code}")
    print(response.json())


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        await asyncio.gather(
            send(
                client,
                "CONCURRENCY-C",
                "CONC-MERCHANT-C",
                "CONC-CHECKOUT-C",
            ),
            send(
                client,
                "CONCURRENCY-D",
                "CONC-MERCHANT-D",
                "CONC-CHECKOUT-D",
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())