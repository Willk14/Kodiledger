"""Application-level FastAPI configuration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.configs.environment import settings
from app.utils.text import split_csv_values


APP_TITLE = "KodiFlow API"
APP_DESCRIPTION = "Multi-tenant M-Pesa Rent Reconciliation & Property Management Engine"
APP_VERSION = "1.0.0"


def configure_cors(app: FastAPI) -> None:
    """Install CORS middleware from the configured allowed origins."""
    allowed_origins = split_csv_values(settings.CORS_ALLOWED_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
