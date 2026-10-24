from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from trend_system.config import get_settings

# For demo/testing without Postgres, allow SQLite fallback
# If DATABASE_URL contains "sqlite", use that; otherwise try Postgres, fallback to sqlite file if connection fails on init

def get_async_engine():
    settings = get_settings()
    url = settings.DATABASE_URL
    # If env var USE_SQLITE is set, force sqlite
    if os.getenv("USE_SQLITE") == "1":
        url = "sqlite+aiosqlite:///./trends.db"
    # Also if Postgres not available and url is postgres, we can still try; failure will be caught at init_db
    try:
        return create_async_engine(url, echo=False, future=True)
    except Exception:
        return create_async_engine("sqlite+aiosqlite:///./trends.db", echo=False, future=True)

def get_async_sessionmaker():
    engine = get_async_engine()
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

def get_sync_engine():
    settings = get_settings()
    url = settings.SYNC_DATABASE_URL
    if os.getenv("USE_SQLITE") == "1":
        url = "sqlite:///./trends.db"
    return create_engine(url, echo=False, future=True)

async def init_db():
    from trend_system.database.models import Base
    engine = get_async_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # Fallback to sqlite if postgres fails
        import logging
        logging.getLogger(__name__).warning(f"init_db with primary URL failed: {e}, falling back to sqlite")
        from sqlalchemy.ext.asyncio import create_async_engine as cae
        engine2 = cae("sqlite+aiosqlite:///./trends.db", echo=False, future=True)
        async with engine2.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
