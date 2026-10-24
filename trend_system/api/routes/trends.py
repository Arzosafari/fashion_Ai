from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timezone

from trend_system.database.session import get_async_sessionmaker
from trend_system.database.models import Trend, TrendSnapshot, TrendHistory, TrendEvidence
from trend_system.utils.calendar import to_jalali_dict

router = APIRouter(prefix="/trends", tags=["trends"])

async def get_session():
    async with get_async_sessionmaker()() as session:
        yield session

@router.get("/current")
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
    if season:
        pass
    filtered = filtered[:limit]
    return {
        "snapshot_time_utc": snap.snapshot_time_utc.isoformat(),
        "snapshot_time_jalali": snap.snapshot_time_jalali,
        "season": snap.season,
        "trends": filtered,
        "meta": {"scoring_version": snap.scoring_version, "scoring_mode": snap.scoring_mode, "total": len(trends), "stale_warning": None}
    }

@router.post("/refresh")
async def refresh(limit: int = 10, session: AsyncSession = Depends(get_session)):
    """On-demand: collect newest from global sources + snapshot"""
    from trend_system.scheduler.snapshot import materialize_snapshot
    try:
        from scripts.run_collector import live_run
        await live_run(limit_per_source=limit, exclude_synthetic=True)
    except Exception:
        pass
    snap = await materialize_snapshot(session, datetime.now(timezone.utc), exclude_synthetic=True)
    return {"refreshed_at": datetime.now(timezone.utc).isoformat(), "total": len(snap), "trends": snap[:limit]}

@router.get("/for-recommendation")
async def for_recommendation(
    season: str | None = None,
    limit: int = Query(10, ge=1, le=50),
    gender: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(TrendSnapshot).order_by(desc(TrendSnapshot.snapshot_time_utc)).limit(1))
    snap = result.scalars().first()
    if not snap:
        return {"snapshot_time_utc": None, "trends": []}
    trends = [t for t in snap.trends if t.get("is_actionable")]
    if season:
        trends = sorted(trends, key=lambda x: (x.get("trend_score",0) * (x.get("seasonal_relevance") if x.get("seasonal_relevance") else 1)), reverse=True)
    else:
        trends = sorted(trends, key=lambda x: x.get("trend_score",0), reverse=True)
    return {
        "snapshot_time_utc": snap.snapshot_time_utc.isoformat(),
        "snapshot_time_jalali": snap.snapshot_time_jalali,
        "season": season or snap.season,
        "trends": trends[:limit],
        "meta": {"scoring_version": snap.scoring_version}
    }

@router.get("")
async def list_trends(
    q: str | None = None,
    category: str | None = None,
    lifecycle: str | None = None,
    iran_min: float | None = None,
    global_min: float | None = None,
    trend_scope: str | None = None,
    sort: str = "current_score",
    order: str = "desc",
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    query = select(Trend)
    if category:
        query = query.where(Trend.category == category)
    if lifecycle:
        query = query.where(Trend.lifecycle_state == lifecycle)
    if iran_min is not None:
        query = query.where(Trend.iran_relevance_score >= iran_min)
    if global_min is not None:
        query = query.where(Trend.global_score >= global_min)
    if trend_scope:
        if hasattr(Trend, "trend_scope"):
            query = query.where(Trend.trend_scope == trend_scope)
    else:
        if hasattr(Trend, "trend_scope"):
            query = query.where((Trend.trend_scope == "global") | (Trend.trend_scope.is_(None)))
    if q:
        query = query.where(Trend.canonical_name.ilike(f"%{q}%"))
    if sort == "current_score":
        col = Trend.current_score
    elif sort == "iran_relevance":
        col = Trend.iran_relevance_score
    else:
        col = Trend.current_score
    if order == "desc":
        query = query.order_by(desc(col))
    else:
        query = query.order_by(col)
    query = query.limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()
    return {"trends": [
        {
            "trend": r.canonical_name,
            "canonical_name": r.canonical_name,
            "category": r.category,
            "trend_score": r.current_score,
            "current_score": r.current_score,
            "iran_relevance": r.iran_relevance_score,
            "global_strength": r.global_score,
            "lifecycle": r.lifecycle_state,
            "confidence": r.recency_score,
            "last_updated": r.last_seen_utc.isoformat() if r.last_seen_utc else None,
            "last_updated_jalali": r.last_seen_jalali,
            "evidence_count": r.evidence_count,
            "supporting_sources": r.supporting_sources,
            "is_actionable": r.is_actionable,
            "explanation": r.explanation,
            "components": {"G":r.global_score,"I":r.iran_relevance_score,"R":r.recency_score,"Gw":r.growth_score,"C":r.cross_source_score,"S":r.seasonal_relevance}
        } for r in rows
    ]}

@router.get("/by-name/{canonical_name}")
async def get_by_name(canonical_name: str, session: AsyncSession = Depends(get_session)):
    trend = await session.get(Trend, canonical_name)
    if not trend:
        raise HTTPException(404, "trend not found")
    result = await session.execute(select(TrendEvidence).where(TrendEvidence.trend_id==canonical_name).order_by(desc(TrendEvidence.timestamp_utc)).limit(5))
    evs = result.scalars().all()
    top_evidence = [{"source_id": e.source_id, "url": f"/raw/{e.raw_document_id}", "date_utc": e.timestamp_utc.isoformat() if e.timestamp_utc else None, "snippet": e.snippet} for e in evs]
    return {
        "trend": trend.canonical_name,
        "canonical_name": trend.canonical_name,
        "category": trend.category,
        "trend_score": trend.current_score,
        "current_score": trend.current_score,
        "iran_relevance": trend.iran_relevance_score,
        "global_strength": trend.global_score,
        "lifecycle": trend.lifecycle_state,
        "confidence": trend.recency_score,
        "last_updated": trend.last_seen_utc.isoformat() if trend.last_seen_utc else None,
        "last_updated_jalali": trend.last_seen_jalali,
        "evidence_count": trend.evidence_count,
        "supporting_sources": trend.supporting_sources,
        "is_actionable": trend.is_actionable,
        "explanation": trend.explanation,
        "components": {"G":trend.global_score,"I":trend.iran_relevance_score,"R":trend.recency_score,"Gw":trend.growth_score,"C":trend.cross_source_score,"S":trend.seasonal_relevance},
        "top_evidence": top_evidence,
    }

@router.get("/history/{trend_id}")
async def get_history(trend_id: str, from_date: str | None = None, to_date: str | None = None, session: AsyncSession = Depends(get_session)):
    query = select(TrendHistory).where(TrendHistory.trend_id==trend_id).order_by(TrendHistory.snapshot_time_utc)
    result = await session.execute(query)
    rows = result.scalars().all()
    filtered=[]
    for r in rows:
        if from_date:
            try:
                fd = datetime.fromisoformat(from_date.replace("Z","+00:00"))
                if r.snapshot_time_utc < fd:
                    continue
            except: pass
        if to_date:
            try:
                td = datetime.fromisoformat(to_date.replace("Z","+00:00"))
                if r.snapshot_time_utc > td:
                    continue
            except: pass
        filtered.append(r)
    return {"trend_id": trend_id, "history": [
        {
            "snapshot_time_utc": r.snapshot_time_utc.isoformat(),
            "snapshot_time_jalali": r.snapshot_time_jalali,
            "current_score": r.current_score,
            "global_score": r.global_score,
            "iran_relevance_score": r.iran_relevance_score,
            "lifecycle_state": r.lifecycle_state,
            "evidence_count": r.evidence_count,
            "supporting_sources": r.supporting_sources,
        } for r in filtered
    ]}

@router.get("/{trend_id}")
async def get_by_id(trend_id: str, session: AsyncSession = Depends(get_session)):
    return await get_by_name(trend_id, session)