"""Backward-compatible imports; database setup lives in :mod:`app.configs`."""

from app.configs.database import (
    AsyncSessionLocal,
    SystemSessionLocal,
    engine,
    get_db,
    get_system_db,
)

__all__ = [
    "AsyncSessionLocal",
    "SystemSessionLocal",
    "engine",
    "get_db",
    "get_system_db",
]
