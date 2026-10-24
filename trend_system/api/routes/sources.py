from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from trend_system.database.session import get_async_sessionmaker
from trend_system.database.models import Source, SourceHealth, CollectionRun

router = APIRouter(prefix="/sources", tags=["sources"])

async def get_session():
    async with get_async_sessionmaker()() as session:
        yield session

@router.get("")
async def list_sources(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Source))
    rows = result.scalars().all()
    return {"sources": [{"source_id":r.source_id,"name":r.name,"enabled":r.enabled,"authority_weight":r.authority_weight,"update_frequency":r.update_frequency,"last_successful_fetch":r.last_successful_fetch.isoformat() if r.last_successful_fetch else None} for r in rows]}

@router.get("/{source_id}/health")
async def source_health(source_id: str, session: AsyncSession = Depends(get_session)):
    health = await session.get(SourceHealth, source_id)
    if not health:
        return {"source_id": source_id, "is_healthy": True, "consecutive_failures":0}
    return {"source_id": source_id, "is_healthy": health.is_healthy, "consecutive_failures": health.consecutive_failures, "last_error": health.last_error, "last_success": health.last_success.isoformat() if health.last_success else None, "circuit_open_until": health.circuit_open_until.isoformat() if health.circuit_open_until else None}

@router.get("/runs/history")
async def collection_runs(limit: int = 20, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(limit))
    rows = result.scalars().all()
    return {"runs": [{"id":r.id,"started_at":r.started_at.isoformat() if r.started_at else None,"finished_at":r.finished_at.isoformat() if r.finished_at else None,"sources_checked":r.sources_checked,"sources_successful":r.sources_successful,"new_documents":r.new_documents,"status":r.status} for r in rows]}
