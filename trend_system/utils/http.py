"""Shared HTTP client factory for collectors and ingestion."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx

from trend_system.config import get_settings


def _default_headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "User-Agent": settings.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }


@asynccontextmanager
async def get_http_client(timeout: float | None = None, **kwargs):
    """Yield a configured ``httpx.AsyncClient``.

    Redirects are followed (publishers frequently redirect legacy URLs) and
    connection reuse is bounded so a single slow host cannot exhaust sockets.
    """
    settings = get_settings()
    effective_timeout = timeout if timeout is not None else float(settings.DEFAULT_TIMEOUT)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(
        headers=_default_headers(),
        timeout=httpx.Timeout(effective_timeout),
        follow_redirects=True,
        limits=limits,
        **kwargs,
    ) as client:
        yield client
