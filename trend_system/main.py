"""Standalone FastAPI application for the Global Fashion Trend Module.

The integrated Fashion AI application mounts the same router
(``trend_system.api.router.api_router``) from ``fashion_stt.server``; this app
exists so the module can be run, tested and deployed independently.

Run with::

    uvicorn trend_system.main:app --port 8001

Endpoints
---------
``GET  /api/v1/trends/current``              current materialized snapshot
``GET  /api/v1/trends/for-recommendation``   actionable trends, ranked
``GET  /api/v1/trends/context``              compact context for the NLU layer
``GET  /api/v1/trends``                      trend table query
``GET  /api/v1/trends/{trend_id}``           trend + top evidence
``GET  /api/v1/sources``                     configured sources
``GET  /health``                             module + database health
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from trend_system.api.router import api_router
from trend_system.bootstrap import bootstrap_trend_module
from trend_system.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise schema/reference data once at startup (never destructive)."""
    try:
        info = await bootstrap_trend_module()
    except Exception as exc:  # pragma: no cover - depends on deployment
        logger.exception("Trend module bootstrap failed: %s", exc)
        info = {"status": "failed", "error": str(exc)}
    app.state.trend_bootstrap = info
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO))

    app = FastAPI(
        title="Fashion Trend Intelligence Pipeline",
        description=(
            "Global fashion trend collection, extraction, semantic clustering, "
            "scoring and snapshots (Vogue, Harper's Bazaar, Who What Wear; WGSN "
            "only when legally accessible)."
        ),
        version="2.0.0-global",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def health():
        from trend_system.service import get_module_status

        module = await get_module_status()
        return {
            "status": "healthy" if module.get("available") else "degraded",
            "module": "Global Fashion Trend Module",
            "version": "2.0.0-global",
            "database": "sqlite" if str(settings.DATABASE_URL).startswith("sqlite") else "external",
            "trend_module": module,
            "collection_scope": "global",
            "sources": ["vogue", "harpers_bazaar", "whowhatwear", "wgsn"],
        }

    return app


app = create_app()
