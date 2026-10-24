"""Shared FastAPI dependencies for the trend routers."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from trend_system.bootstrap import bootstrap_trend_module
from trend_system.database.session import get_async_sessionmaker

logger = logging.getLogger(__name__)


async def ensure_trend_db() -> None:
    """Create/seed the trend database on first use (idempotent, process-wide)."""
    try:
        await bootstrap_trend_module()
    except Exception as exc:  # pragma: no cover - depends on deployment
        logger.exception("Trend database initialization failed")
        raise HTTPException(
            status_code=503,
            detail=f"Trend module database is unavailable: {exc}",
        ) from exc


async def get_session() -> AsyncSession:
    """Yield a SQLAlchemy async session for a single request."""
    async with get_async_sessionmaker()() as session:
        yield session
