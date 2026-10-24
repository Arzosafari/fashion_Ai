"""Opt-in background worker: periodic trend collection + snapshot.

Usage::

    TREND_SCHEDULER_ENABLED=1 python scripts/schedule_trends.py

The scheduler is intentionally **not** started by the API process.  Job ids are
registered idempotently, so running this twice in one process cannot create
duplicate recurring jobs.
"""

from __future__ import annotations

import asyncio
import logging

from trend_system.scheduler.jobs import start_scheduler

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    scheduler = start_scheduler()
    if scheduler is None:
        print("Trend scheduler disabled. Set TREND_SCHEDULER_ENABLED=1 to enable.")
        return
    print(f"Scheduler running with jobs: {[job.id for job in scheduler.get_jobs()]}")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
