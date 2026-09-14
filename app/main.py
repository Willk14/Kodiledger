from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.webhooks import router as webhooks_router
from app.api.v1.endpoints.payments import router as payments_router
from app.api.v1.endpoints.Bff.landlord import (
    router as landlord_bff_router,
)
from app.api.v1.endpoints.Bff.caretaker import (
    router as caretaker_bff_router,
)
from app.core.config import settings


# ============================================================
# Application
# ============================================================

app = FastAPI(
    title="KodiFlow API",
    description=(
        "Multi-tenant M-Pesa Rent Reconciliation "
        "& Property Management Engine"
    ),
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

allowed_origins = [
    origin.strip()
    for origin in settings.CORS_ALLOWED_ORIGINS.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


# ============================================================
# API Routers
# ============================================================

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

app.include_router(
    landlord_bff_router,
    prefix="/api/v1",
    tags=["Landlord"],
)

app.include_router(
    caretaker_bff_router,
    prefix="/api/v1",
    tags=["Caretaker"],
)


# ============================================================
# Root / Health
# ============================================================

@app.get("/", tags=["System"])
async def root() -> dict[str, str]:
    return {
        "status": "online",
        "system": "KodiFlow Backend Engine",
    }

