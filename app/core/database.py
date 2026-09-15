from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _create_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_recycle=300,
    )


# ------------------------------------------------------------
# Normal application database
# kodiflow_app -> RLS enforced
# ------------------------------------------------------------

engine = _create_engine(settings.DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ------------------------------------------------------------
# Privileged system database
# kodiflow_system -> used only by system/webhook workflows
# ------------------------------------------------------------

system_engine = _create_engine(settings.SYSTEM_DATABASE_URL)

SystemSessionLocal = async_sessionmaker(
    system_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ------------------------------------------------------------
# FastAPI dependencies
# ------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_system_db() -> AsyncGenerator[AsyncSession, None]:
    async with SystemSessionLocal() as session:
        yield session
