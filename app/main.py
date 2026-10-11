from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.controllers.webhooks import router as webhooks_router
from app.controllers.payments import router as payments_router
from app.controllers.properties import router as properties_router
from app.controllers.units import router as units_router
from app.controllers.tenants import router as tenants_router
from app.controllers.invoices import router as invoices_router
from app.controllers.unassigned_payments import router as unassigned_payments_router
from app.controllers.ledger import router as ledger_router
from app.controllers.system import router as system_router
from app.controllers.bff.landlord import (
    router as landlord_bff_router,
)
from app.controllers.bff.caretaker import (
    router as caretaker_bff_router,
)
from app.configs.app import (
    APP_DESCRIPTION,
    APP_TITLE,
    APP_VERSION,
    configure_cors,
)
from app.configs.database import engine, system_engine


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
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================

configure_cors(app)


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

app.include_router(system_router)

