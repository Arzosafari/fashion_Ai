"""Database engine/session factory for the trend module.

SQLite is the preserved default (``trends.db`` in the repository root); the
module never requires PostgreSQL.  A ``DATABASE_URL`` override is still honoured
for deployments that provide one.

Engines are cached per URL so that a request does not build a new connection
pool on every call.  SQLite uses ``NullPool`` because connections must not be
shared across event loops (the test-suite creates one loop per test).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from trend_system.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

_DEFAULT_SQLITE_PATH = BASE_DIR / "trends.db"
_INITIALIZED_URLS: set[str] = set()


def default_async_url() -> str:
    return f"sqlite+aiosqlite:///{_DEFAULT_SQLITE_PATH}"


def default_sync_url() -> str:
    return f"sqlite:///{_DEFAULT_SQLITE_PATH}"


def get_database_url() -> str:
    if os.getenv("USE_SQLITE") == "1":
        return default_async_url()
    try:
        url = get_settings().DATABASE_URL
    except Exception:  # pragma: no cover - settings always available
        url = None
    return url or default_async_url()


def get_sync_database_url() -> str:
    if os.getenv("USE_SQLITE") == "1":
        return default_sync_url()
    try:
        url = get_settings().SYNC_DATABASE_URL
    except Exception:  # pragma: no cover
        url = None
    if url:
        return url
    # Derive a sync URL from the async one when only DATABASE_URL is configured.
    async_url = get_database_url()
    return async_url.replace("+aiosqlite", "")


@lru_cache(maxsize=8)
def _build_async_engine(url: str):
    kwargs = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        kwargs["poolclass"] = NullPool
    return create_async_engine(url, **kwargs)


@lru_cache(maxsize=8)
def _build_sessionmaker(url: str):
    return async_sessionmaker(_build_async_engine(url), expire_on_commit=False, class_=AsyncSession)


def get_async_engine():
    return _build_async_engine(get_database_url())


def get_async_sessionmaker():
    """Return an ``async_sessionmaker`` bound to a cached engine."""
    return _build_sessionmaker(get_database_url())


@lru_cache(maxsize=8)
def _build_sync_engine(url: str):
    kwargs = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def get_sync_engine():
    return _build_sync_engine(get_sync_database_url())


def add_missing_columns(sync_connection) -> list[str]:
    """Safely add columns introduced after a database was created.

    ``Base.metadata.create_all`` only creates missing *tables*; existing SQLite
    databases (e.g. the historical ``trends.db`` shipped with the module) would
    otherwise miss newer columns.  Additive ``ALTER TABLE ... ADD COLUMN``
    statements are reversible and preserve every existing row.
    """
    from trend_system.database.models import Base

    dialect = sync_connection.dialect
    inspector = inspect(sync_connection)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns or column.primary_key:
                continue
            try:
                col_type = column.type.compile(dialect=dialect)
            except Exception:
                col_type = "TEXT"
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            default = column.default.arg if column.default is not None and not column.default.is_callable else None
            if isinstance(default, str):
                ddl += f" DEFAULT '{default}'"
            elif isinstance(default, bool):
                ddl += f" DEFAULT {1 if default else 0}"
            elif isinstance(default, (int, float)):
                ddl += f" DEFAULT {default}"
            sync_connection.execute(text(ddl))
            added.append(f"{table.name}.{column.name}")
    return added


async def init_db() -> None:
    """Create tables / add missing columns once per process and database URL."""
    url = get_database_url()
    if url in _INITIALIZED_URLS:
        return

    from trend_system.database.models import Base

    engine = get_async_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            added = await conn.run_sync(add_missing_columns)
            if added:
                logger.info("Added missing trend columns: %s", ", ".join(added))
        _INITIALIZED_URLS.add(url)
    except Exception as exc:
        logger.warning("init_db with primary URL failed: %s", exc)
        if url.startswith("sqlite"):
            raise
        # Preserve the historical fallback for deployments without Postgres.
        fallback_url = default_async_url()
        fallback = _build_async_engine(fallback_url)
        async with fallback.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(add_missing_columns)
        logger.warning("Fell back to SQLite database at %s", _DEFAULT_SQLITE_PATH)
        _INITIALIZED_URLS.add(url)


def reset_engine_cache() -> None:
    """Drop cached engines (used by scripts/tests that switch databases)."""
    _build_async_engine.cache_clear()
    _build_sessionmaker.cache_clear()
    _build_sync_engine.cache_clear()
    _INITIALIZED_URLS.clear()
