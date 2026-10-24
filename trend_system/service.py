"""Read-only service interface for the rest of the Fashion AI application.

The request-understanding layer (and, later, the recommendation engine) must not
reach into trend tables directly.  These helpers expose the latest materialized
snapshot as plain, documented dictionaries and degrade gracefully when the
trend database is empty, missing or temporarily unavailable.

Nothing here generates outfit recommendations — it only surfaces trend context.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

from trend_system.bootstrap import bootstrap_trend_module
from trend_system.database.models import Source, Trend, TrendEvidence, TrendSnapshot
from trend_system.database.session import get_async_sessionmaker

logger = logging.getLogger(__name__)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return str(value)


def _lean_trend(item: dict) -> dict:
    """Reduce a snapshot entry to the fields the recommendation engine needs."""
    return {
        "canonical_name": item.get("canonical_name") or item.get("trend"),
        "category": item.get("category"),
        "trend_score": item.get("trend_score", item.get("current_score")),
        "lifecycle": item.get("lifecycle"),
        "supporting_sources": item.get("supporting_sources"),
        "evidence_count": item.get("evidence_count"),
        "is_actionable": item.get("is_actionable"),
        "seasonal_relevance": item.get("seasonal_relevance"),
        "explanation": item.get("explanation"),
    }


async def _latest_snapshot_row(session):
    result = await session.execute(
        select(TrendSnapshot).order_by(TrendSnapshot.snapshot_time_utc.desc()).limit(1)
    )
    return result.scalars().first()


async def get_trends_for_recommendation(
    limit: int = 10,
    season: str | None = None,
    actionable_only: bool = True,
) -> dict:
    """Return the current trend snapshot, ranked for downstream consumption.

    Response shape (stable contract)::

        {
          "available": bool,
          "status": "ok" | "no_snapshot" | "unavailable",
          "message": str | None,
          "snapshot_time_utc": str | None,
          "snapshot_time_jalali": str | None,
          "season": str | None,
          "trends": [ {canonical_name, category, trend_score, lifecycle, ...} ],
          "meta": {"scoring_version": str | None, "scoring_mode": str | None, "total": int}
        }
    """
    try:
        await bootstrap_trend_module()
        async with get_async_sessionmaker()() as session:
            snapshot = await _latest_snapshot_row(session)
    except Exception as exc:
        logger.warning("Trend snapshot unavailable: %s", exc)
        return {
            "available": False,
            "status": "unavailable",
            "message": f"Trend database unavailable: {exc}",
            "snapshot_time_utc": None,
            "snapshot_time_jalali": None,
            "season": None,
            "trends": [],
            "meta": {},
        }

    if snapshot is None:
        return {
            "available": False,
            "status": "no_snapshot",
            "message": "No trend snapshot has been materialized yet.",
            "snapshot_time_utc": None,
            "snapshot_time_jalali": None,
            "season": None,
            "trends": [],
            "meta": {},
        }

    items = list(snapshot.trends or [])
    selected = items
    if actionable_only:
        actionable = [t for t in items if t.get("is_actionable")]
        # If nothing is actionable yet (small dataset), fall back to the ranked
        # list so consumers still receive evidence-backed trends.
        selected = actionable or items

    if season:
        normalized = season.lower()
        matching = [
            t
            for t in selected
            if str(t.get("season", "")).lower() == normalized
            or normalized in str(t.get("explanation", "")).lower()
        ]
        if matching:
            selected = matching

    selected = sorted(
        selected,
        key=lambda t: (t.get("trend_score") or t.get("current_score") or 0.0),
        reverse=True,
    )[: max(1, min(int(limit), 50))]

    return {
        "available": True,
        "status": "ok",
        "message": None,
        "snapshot_time_utc": _iso(snapshot.snapshot_time_utc),
        "snapshot_time_jalali": snapshot.snapshot_time_jalali,
        "season": season or snapshot.season,
        "trends": selected,
        "meta": {
            "scoring_version": snapshot.scoring_version,
            "scoring_mode": snapshot.scoring_mode,
            "total": len(items),
        },
    }


async def get_trend_context(limit: int = 5) -> dict:
    """Compact trend context for the existing request-understanding pipeline."""
    result = await get_trends_for_recommendation(limit=limit, actionable_only=True)
    return {
        "available": result["available"],
        "status": result["status"],
        "message": result.get("message"),
        "snapshot_time_utc": result.get("snapshot_time_utc"),
        "season": result.get("season"),
        "trends": [_lean_trend(item) for item in result.get("trends", [])],
        "meta": result.get("meta", {}),
    }


async def get_module_status() -> dict:
    """Health/introspection payload (used by ``/health`` and the app health check)."""
    try:
        await bootstrap_trend_module()
        async with get_async_sessionmaker()() as session:
            snapshot = await _latest_snapshot_row(session)
            trend_count = (await session.execute(select(func.count()).select_from(Trend))).scalar() or 0
            evidence_count = (
                await session.execute(select(func.count()).select_from(TrendEvidence))
            ).scalar() or 0
            enabled_sources = (
                await session.execute(select(func.count()).select_from(Source).where(Source.enabled == True))  # noqa: E712
            ).scalar() or 0
        return {
            "available": True,
            "status": "ok",
            "trends": int(trend_count),
            "evidence": int(evidence_count),
            "enabled_sources": int(enabled_sources),
            "latest_snapshot": _iso(snapshot.snapshot_time_utc) if snapshot else None,
            "scoring_version": snapshot.scoring_version if snapshot else None,
            "scoring_mode": snapshot.scoring_mode if snapshot else None,
        }
    except Exception as exc:
        logger.warning("Trend module status unavailable: %s", exc)
        return {"available": False, "status": "unavailable", "message": str(exc)}
