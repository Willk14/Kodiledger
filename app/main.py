from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.endpoints.webhooks import router as webhooks_router
from app.api.v1.endpoints.payments import router as payments_router
from app.api.v1.endpoints.properties import router as properties_router
from app.api.v1.endpoints.units import router as units_router
from app.api.v1.endpoints.tenants import router as tenants_router
from app.api.v1.endpoints.invoices import router as invoices_router
from app.api.v1.endpoints.unassigned_payments import router as unassigned_payments_router
from app.api.v1.endpoints.ledger import router as ledger_router
from app.api.v1.endpoints.Bff.landlord import (
    router as landlord_bff_router,
)
from app.api.v1.endpoints.Bff.caretaker import (
    router as caretaker_bff_router,
)
from app.core.config import settings
from app.core.database import engine, system_engine


async def _check_database_connection(database_engine: AsyncEngine, name: str) -> None:
    try:
        async with database_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        # Do not include the connection URL in startup errors or logs.
        raise RuntimeError(f"Could not connect to the {name} database.") from None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        # Validate both configured PostgreSQL roles before serving requests.
        await _check_database_connection(engine, "application")
        await _check_database_connection(system_engine, "system")
        yield
    finally:
        await engine.dispose()
        await system_engine.dispose()


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
    lifespan=lifespan,
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
    properties_router,
    prefix="/api/v1",
)

app.include_router(
    units_router,
    prefix="/api/v1",
)

app.include_router(
    tenants_router,
    prefix="/api/v1",
)

app.include_router(
    invoices_router,
    prefix="/api/v1",
)

app.include_router(
    unassigned_payments_router,
    prefix="/api/v1",
)

app.include_router(
    ledger_router,
    prefix="/api/v1",
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

