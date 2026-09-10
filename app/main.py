from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.webhooks import router as webhooks_router
from app.api.v1.endpoints.payments import router as payments_router


app = FastAPI(
    title="KodiFlow API",
    description="Multi-tenant M-Pesa Rent Reconciliation & Property Management Engine",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    webhooks_router,
    prefix="/api/v1/webhooks",
    tags=["Webhooks"],
)

app.include_router(
    payments_router,
    prefix="/api/v1",
    tags=["Payments"],
)


@app.get("/")
async def root():
    return {
        "status": "online",
        "system": "KodiFlow Backend Engine",
    }

  

    