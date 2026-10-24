"""Aggregate API router for the Global Fashion Trend module.

Mounted by both the standalone trend app (``trend_system.main``) and the
existing Fashion AI application (``fashion_stt.server``) under ``/api/v1``.
"""

from __future__ import annotations

from fastapi import APIRouter

from trend_system.api.routes import sources, trends

api_router = APIRouter()
api_router.include_router(trends.router)
api_router.include_router(sources.router)

__all__ = ["api_router"]
