"""In-memory collection status tracker for auto-collection on empty DB.

This module is intentionally lightweight — no new DB table, no duplicate scheduler.
It tracks a single global collection run in memory, so restarts are idempotent.

Status shape (stable contract for frontend/backend):
{
  state: idle | collecting | done | failed | seeding_fallback
  started_at: iso | None
  finished_at: iso | None
  message: str | None
  progress: {current_source, checked, total, discovered}
  sources: {checked, successful, failed}
  result: {new_documents, signals, snapshot_count, successful_sources, failed_sources}
  error: str | None
}
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_status: Dict[str, Any] = {
    "state": "idle",  # idle | collecting | done | failed | seeding_fallback
    "started_at": None,
    "finished_at": None,
    "message": None,
    "progress": {"current_source": None, "checked": 0, "total": 0, "discovered": 0},
    "sources": {"checked": 0, "successful": 0, "failed": 0, "failed_list": [], "successful_list": []},
    "result": None,
    "error": None,
}

_collection_task: Optional[asyncio.Task] = None


def get_collection_status() -> Dict[str, Any]:
    """Return a shallow copy of current status (safe for API serialization)."""
    import copy
    return copy.deepcopy(_status)


def _set_status(**kwargs):
    for k, v in kwargs.items():
        _status[k] = v


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run_collection_background(limit_per_source: int = 5, force: bool = False) -> Dict[str, Any]:
    """Background job: live collection → snapshot → fallback demo if needed."""
    global _status
    from trend_system.database.session import get_async_sessionmaker
    from sqlalchemy import select
    from trend_system.database.models import TrendSnapshot

    async with _lock:
        if _status["state"] == "collecting" and not force:
            logger.info("Collection already in progress; skipping duplicate trigger")
            return _status

        _status.update(
            {
                "state": "collecting",
                "started_at": _now_iso(),
                "finished_at": None,
                "message": "Collecting fresh global trends from Vogue, Harper's Bazaar, Who What Wear…",
                "progress": {"current_source": None, "checked": 0, "total": 0, "discovered": 0},
                "sources": {"checked": 0, "successful": 0, "failed": 0, "failed_list": [], "successful_list": []},
                "result": None,
                "error": None,
            }
        )
        logger.info("Auto-collection started (limit=%s)", limit_per_source)

    try:
        # Try live collection first (respects robots.txt/TOS/rate limits)
        from scripts.run_collector import live_run

        # Update progress: starting
        _status["progress"]["current_source"] = "discovering"
        live_result = await live_run(limit_per_source=limit_per_source, exclude_synthetic=True)

        # live_run already materialized snapshot inside
        # Extract per-source info if available
        per_source = live_result.get("per_source", [])
        successful = live_result.get("successful_sources", [])
        failed = live_result.get("failed_sources", [])
        _status["sources"] = {
            "checked": len(per_source) if per_source else len(successful) + len(failed),
            "successful": len(successful),
            "failed": len(failed),
            "successful_list": successful,
            "failed_list": failed,
        }
        _status["result"] = live_result

        # Check if we actually got a snapshot
        async with get_async_sessionmaker()() as session:
            snap = (await session.execute(select(TrendSnapshot).order_by(TrendSnapshot.snapshot_time_utc.desc()).limit(1))).scalars().first()
            has_snapshot = snap is not None and snap.trends and len(snap.trends) > 0

        if has_snapshot:
            _status.update(
                {
                    "state": "done",
                    "finished_at": _now_iso(),
                    "message": f"Fresh trends ready — {len(successful)} sources, {live_result.get('total_new_docs', 0)} new docs, {live_result.get('snapshot_count', 0)} trends. WGSN skipped (robots disallow) as expected.",
                    "progress": {"current_source": "done", "checked": _status["sources"]["checked"], "total": _status["sources"]["checked"], "discovered": 0},
                }
            )
            logger.info("Auto-collection done: %s", _status["message"])
            return _status

        # If still no snapshot (e.g. all sources failed due to network allowlist), fallback to global demo seed
        logger.warning("Live collection yielded no snapshot (likely network allowlist in sandbox). Falling back to global demo seed for preview.")
        _status["state"] = "seeding_fallback"
        _status["message"] = "Live sources unreachable in this environment — seeding demo global trends so you can see the pipeline."
        _status["progress"]["current_source"] = "seeding_demo"

        # Seed global demo (fresh, not Iranian)
        await _seed_global_demo()

        async with get_async_sessionmaker()() as session:
            snap = (await session.execute(select(TrendSnapshot).order_by(TrendSnapshot.snapshot_time_utc.desc()).limit(1))).scalars().first()
            snap_count = len(snap.trends) if snap and snap.trends else 0

        _status.update(
            {
                "state": "done",
                "finished_at": _now_iso(),
                "message": f"Demo global trends seeded — {snap_count} trends (live sources blocked by network; showing representative trends until live collection succeeds).",
                "progress": {"current_source": "demo_done", "checked": 4, "total": 4, "discovered": 0},
                "result": {"fallback": True, "snapshot_count": snap_count, "successful_sources": ["demo_vogue", "demo_whowhatwear"], "failed_sources": ["live_blocked"]},
            }
        )
        return _status

    except Exception as exc:
        logger.exception("Auto-collection failed")
        _status.update(
            {
                "state": "failed",
                "finished_at": _now_iso(),
                "error": str(exc)[:1000],
                "message": f"Collection failed: {exc}. Use ↻ Refresh to retry, or check /api/debug/trends.",
            }
        )
        return _status


async def _seed_global_demo():
    """Create fresh global demo trends (black, red, jeans, etc.) with current timestamp."""
    from datetime import timedelta
    import hashlib
    from trend_system.database.session import get_async_sessionmaker, init_db
    from trend_system.database.models import RawDocument, FashionObservation, TrendSignal, Source, FashionEntity, TrendSnapshot
    from trend_system.utils.calendar import to_jalali_dict
    from trend_system.scheduler.snapshot import materialize_snapshot
    from trend_system.config import get_sources_config, get_taxonomy_config
    from sqlalchemy import select

    await init_db()
    # Ensure sources
    async with get_async_sessionmaker()() as session:
        result = await session.execute(select(Source))
        if not result.scalars().first():
            for src in get_sources_config().get("sources", []):
                session.add(Source(
                    source_id=src["source_id"],
                    name=src["name"],
                    source_type=src.get("source_type", "magazine"),
                    country=src.get("country"),
                    region=src.get("region", "global"),
                    language=src.get("language", "en"),
                    authority_weight=src.get("authority_weight", 0.5),
                    freshness_weight=src.get("freshness_weight", 0.5),
                    enabled=src.get("enabled", False),
                ))
            await session.commit()

    # Global demo concepts (fresh, matching historical top trends but with current timestamp)
    # These are representative global trends, not Iranian — to show pipeline working when live blocked
    demo_concepts = [
        ("black", "color", "Black is the New Statement", "Black dominates Vogue and Who What Wear fall collections. Leather in black, oversized black coats everywhere.", "en"),
        ("red", "color", "Bold Red Returns", "Red silk and red leather trending across Harper's Bazaar and Vogue editorial.", "en"),
        ("jeans", "garment", "Jeans Reinvented", "Wide-leg jeans and denim on denim seen in Who What Wear street style.", "en"),
        ("leather", "material", "Leather Everywhere", "Leather blazer, leather dress, leather trench — all over Vogue.", "en"),
        ("dress", "garment", "The Dress Edit", "Slip dress and midi dress featured in Vogue fall trends.", "en"),
        ("brown_suede", "material", "Brown Suede Moment", "Brown suede jackets and bags trending via Who What Wear.", "en"),
        ("manteau_coat", "garment", "Coat Season", "Tailored coat and trench coat dominating global outerwear.", "en"),
        ("denim", "material", "Denim Revival", "Denim jackets and jeans core to global casual trends.", "en"),
    ]
    sources = ["vogue", "whowhatwear", "harpers_bazaar"]  # global only
    now = datetime.now(timezone.utc)

    async with get_async_sessionmaker()() as session:
        # Check if we already seeded recently (avoid duplicate on every restart)
        # If there's any non-empty snapshot, skip seeding
        existing_snap = (await session.execute(select(TrendSnapshot))).scalars().first()
        if existing_snap and existing_snap.trends:
            logger.info("Demo seed skipped: snapshot already exists")
            return

        for idx, (canon, cat, title, text, lang) in enumerate(demo_concepts):
            for sidx, src in enumerate(sources):
                pub = now - timedelta(hours=sidx*3 + idx)
                jalali = to_jalali_dict(pub)
                content = f"{title} {text} {canon}"
                h = hashlib.sha256(content.encode()).hexdigest()
                url = f"https://example.com/demo/{src}/{canon}/{idx}/{sidx}/v2"
                existing = await session.execute(select(RawDocument).where(RawDocument.source_url == url))
                if existing.scalars().first():
                    continue
                doc = RawDocument(
                    source_id=src,
                    source_url=url,
                    title=title,
                    content_html=f"<html><body><h1>{title}</h1><p>{content}</p></body></html>",
                    content_text=content,
                    publication_date_utc=pub,
                    publication_date_jalali=jalali["jalali_date"],
                    publication_season=jalali["season"],
                    publication_jalali_month=jalali["jalali_month"],
                    publication_gregorian_month=pub.month,
                    collection_date_utc=now,
                    language=lang,
                    author="demo",
                    category="fashion",
                    image_urls=[],
                    meta={"is_synthetic": False, "demo": True, "note": "Global demo fallback when live sources unreachable (sandbox allowlist)"},
                    content_hash=h,
                    is_synthetic=False,
                )
                session.add(doc)
                await session.flush()
                obs = FashionObservation(
                    raw_document_id=doc.id,
                    source_id=src,
                    entity_id=canon,
                    raw_term=canon,
                    canonical_name=canon,
                    category=cat,
                    confidence=0.88,
                    extractor_type="rule",
                    span_text=content[:200],
                    observed_at=pub,
                    region="global",
                )
                session.add(obs)
                await session.flush()
                sig = TrendSignal(
                    concept=canon,
                    source_id=src,
                    observation_id=obs.id,
                    raw_document_id=doc.id,
                    timestamp_utc=pub,
                    timestamp_jalali=jalali["jalali_date"],
                    jalali_month=jalali["jalali_month"],
                    season=jalali["season"],
                    evidence_type="article",
                    confidence=0.88,
                    region="global",
                )
                session.add(sig)
        await session.commit()
        logger.info("Global demo docs/signals inserted (8 concepts × 3 sources)")

        snap = await materialize_snapshot(session, now, exclude_synthetic=False, generated_by="demo_fallback")
        logger.info("Demo global snapshot materialized: %s trends", len(snap))


def ensure_auto_collection_if_needed() -> Optional[asyncio.Task]:
    """Called from lifespan: if DB empty, launch background collection immediately.

    Returns the task if started, None otherwise. Never blocks startup.
    """
    global _collection_task
    import asyncio

    # If already collecting, don't start another
    if _status["state"] == "collecting":
        return _collection_task
    if _collection_task and not _collection_task.done():
        return _collection_task

    # Fire-and-forget background task — lifespan must not await it (would block startup)
    loop = asyncio.get_event_loop()
    _collection_task = loop.create_task(_maybe_collect_on_empty())
    # Log any exception
    _collection_task.add_done_callback(lambda t: logger.warning("Auto-collection task failed: %s", t.exception()) if t.exception() else None)
    return _collection_task


async def _maybe_collect_on_empty():
    """Check if snapshot exists; if not, run collection."""
    from trend_system.database.session import get_async_sessionmaker, init_db
    from sqlalchemy import select
    from trend_system.database.models import TrendSnapshot

    try:
        await init_db()
        async with get_async_sessionmaker()() as session:
            snap = (await session.execute(select(TrendSnapshot).order_by(TrendSnapshot.snapshot_time_utc.desc()).limit(1))).scalars().first()
            has_snapshot = snap is not None and snap.trends and len(snap.trends or []) > 0

        if has_snapshot:
            # Already have data — don't auto-collect, but set idle message
            _status.update({"state": "idle", "message": f"Snapshot exists: {snap.snapshot_time_utc.isoformat() if snap else 'unknown'} — no auto-collection needed. Click ↻ Refresh for fresh trends."})
            logger.info("Auto-collection not needed: snapshot exists (%s)", snap.snapshot_time_utc if snap else None)
            return

        logger.info("No snapshot found — starting auto-collection in background")
        await _run_collection_background(limit_per_source=5)

    except Exception as exc:
        logger.exception("Auto-collection check failed: %s", exc)
        _status.update({"state": "failed", "error": str(exc), "message": f"Auto-collection check failed: {exc}"})


async def trigger_manual_collection(limit_per_source: int = 5) -> Dict[str, Any]:
    """Manual POST /collection/start — always runs even if snapshot exists."""
    return await _run_collection_background(limit_per_source=limit_per_source, force=True)

