from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timezone

from trend_system.api.deps import ensure_trend_db, get_session
from trend_system.api.schemas import (
    TrendContextResponse,
    TrendsForRecommendationResponse,
    TrendsSnapshotResponse,
)
from trend_system.database.models import Trend, TrendSnapshot, TrendHistory, TrendEvidence
from trend_system.service import start_trend_collection

router = APIRouter(
    prefix="/trends",
    tags=["trends"],
    dependencies=[Depends(ensure_trend_db)],
)

@router.post("/start-collection", response_model=dict)
async def start_collection(
    limit_per_source: int | None = Query(None, description="Max URLs per source"),
    exclude_synthetic: bool = Query(True, description="Exclude synthetic seed data"),
):
    """
    Endpoint to trigger collection whenever a new trend cycle starts.
    This calls the collection → ingestion → snapshot pipeline.
    """
    try:
        result = await start_trend_collection(
            limit_per_source=limit_per_source,
            exclude_synthetic=exclude_synthetic
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/current", response_model=TrendsSnapshotResponse)
async def get_current(
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    lifecycle: str | None = None,
    region: str | None = None,
    trend_scope: str | None = Query(None, description="global | iranian (historical)"),
    season: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(TrendSnapshot).order_by(desc(TrendSnapshot.snapshot_time_utc)).limit(1))
    snap = result.scalars().first()
    if not snap:
        return {"snapshot_time_utc": None, "snapshot_time_jalali": None, "trends": [], "meta": {"message": "no snapshot yet"}}
    trends = snap.trends
    filtered = trends
    if category:
        filtered = [t for t in filtered if t.get("category")==category]
    if lifecycle:
        filtered = [t for t in filtered if t.get("lifecycle")==lifecycle]
    if trend_scope == "iranian" or region == "iran":
        filtered = [t for t in filtered if t.get("iran_relevance",0) >= 0.5 or t.get("trend_scope")=="iranian"]
    elif region == "global" or trend_scope == "global":
        filtered = [t for t in filtered if t.get("trend_scope","global")=="global" or t.get("global_strength",0) >= 0]
    if season and (snap.season or "").lower() != season.lower():
        # The snapshot belongs to one season; report it as-is instead of
        # pretending another season's evidence exists.
        filtered = filtered
    filtered = filtered[:limit]
    return {
        "snapshot_time_utc": _iso(snap.snapshot_time_utc),
        "snapshot_time_jalali": _iso(snap.snapshot_time_jalali) if hasattr(snap, 'snapshot_time_jalali') else None,
        "season": snap.season,
        "trends": [_lean_trend(t) for t in filtered],
        "meta": {
            "scoring_version": snap.scoring_version,
            "scoring_mode": snap.scoring_mode,
            "total": len(trends),
            "season_matches_snapshot": (season is None or season.lower() == (snap.season or "").lower())
        },
    }


@router.get("/for-recommendation", response_model=TrendsForRecommendationResponse)
async def get_for_recommendation(
    limit: int = Query(10, ge=1, le=100),
    season: str | None = None,
    actionable_only: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    """Compact trend context for the existing request-understanding pipeline."""
    from trend_system.service import get_trends_for_recommendation, _lean_trend
    result = await get_trends_for_recommendation(limit=limit, season=season, actionable_only=actionable_only)
    
    # Map the result to the schema if needed, or return directly
    # The schema TrendsForRecommendationResponse matches the dict structure
    return result


@router.get("/context", response_model=TrendContextResponse)
async def get_context(
    limit: int = Query(5, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Compact trend context for the existing request-understanding pipeline."""
    from trend_system.service import get_trend_context
    result = await get_trend_context(limit=limit)
    return result


@router.get("/sources")
async def get_sources(session: AsyncSession = Depends(get_session)):
    from trend_system.database.models import Source
    result = await session.execute(select(Source))
    sources = result.scalars().all()
    return [{"source_id": s.source_id, "name": s.name, "enabled": s.enabled} for s in sources]


@router.get("/{trend_id}", response_model=dict)
async def get_trend_detail(
    trend_id: str,
    session: AsyncSession = Depends(get_session),
):
    from trend_system.database.models import Trend, TrendEvidence
    result = await session.execute(select(Trend).where(Trend.canonical_name == trend_id))
    trend = result.scalars().first()
    if not trend:
        raise HTTPException(status_code=404, detail="Trend not found")
    
    ev_result = await session.execute(select(TrendEvidence).where(TrendEvidence.trend_canonical_name == trend_id).limit(5))
    evidences = ev_result.scalars().all()
    
    return {
        "trend": trend.__dict__,
        "top_evidence": [{"id": e.id, "source": e.source_id, "score": e.score} for e in evidences]
    }


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    from trend_system.service import get_module_status
    return await get_module_status()
