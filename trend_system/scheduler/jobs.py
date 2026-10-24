"""Optional background scheduling for collection and snapshots.

There is **no** scheduler running inside the API process.  The existing Fashion
AI application has no scheduler, so this module is opt-in only and is never
started automatically.  Use it from a dedicated worker/CLI process::

    TREND_SCHEDULER_ENABLED=1 python scripts/schedule_trends.py

``configure_jobs`` refuses to register a job id twice, which prevents duplicate
recurring jobs if a process re-runs configuration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from trend_system.config import get_settings

logger = logging.getLogger(__name__)

COLLECTION_JOB_ID = "trend_collection"
SNAPSHOT_JOB_ID = "trend_snapshot"

_scheduler = None


async def collect_and_snapshot(max_urls: int | None = None, exclude_synthetic: bool = True) -> dict:
    """One collection → ingestion → snapshot cycle."""
    from scripts.run_collector import live_run

    settings = get_settings()
    limit = max_urls or int(settings.TREND_COLLECTION_MAX_URLS)
    payload = await live_run(limit_per_source=limit, exclude_synthetic=exclude_synthetic)
    return {"finished_at": datetime.now(timezone.utc).isoformat(), "result": payload}


def configure_jobs(scheduler=None, interval_hours: int | None = None):
    """Register the two recurring jobs exactly once (idempotent)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    global _scheduler
    scheduler = scheduler or _scheduler or AsyncIOScheduler(timezone="UTC")
    _scheduler = scheduler

    settings = get_settings()
    interval = interval_hours or int(settings.TREND_SNAPSHOT_INTERVAL_HOURS)

    if scheduler.get_job(COLLECTION_JOB_ID) is None:
        scheduler.add_job(
            collect_and_snapshot,
            "interval",
            hours=interval,
            id=COLLECTION_JOB_ID,
            replace_existing=False,
            max_instances=1,
            coalesce=True,
        )
    else:
        logger.info("Job %s already registered; skipping", COLLECTION_JOB_ID)

    if scheduler.get_job(SNAPSHOT_JOB_ID) is None:
        scheduler.add_job(
            _snapshot_only,
            "interval",
            hours=interval,
            id=SNAPSHOT_JOB_ID,
            replace_existing=False,
            max_instances=1,
            coalesce=True,
        )
    else:
        logger.info("Job %s already registered; skipping", SNAPSHOT_JOB_ID)
    return scheduler


async def _snapshot_only() -> dict:
    from trend_system.database.session import get_async_sessionmaker
    from trend_system.scheduler.snapshot import materialize_snapshot

    async with get_async_sessionmaker()() as session:
        payload = await materialize_snapshot(
            session, datetime.now(timezone.utc), exclude_synthetic=True, generated_by="scheduler"
        )
    return {"trends": len(payload), "at": datetime.now(timezone.utc).isoformat()}


def start_scheduler():
    """Start the opt-in scheduler (returns None when disabled)."""
    settings = get_settings()
    if not settings.TREND_SCHEDULER_ENABLED:
        logger.info("Trend scheduler disabled (TREND_SCHEDULER_ENABLED != 1)")
        return None
    scheduler = configure_jobs()
    if not scheduler.running:
        scheduler.start()
    return scheduler
