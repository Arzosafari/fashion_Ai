from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime

class TrendComponent(BaseModel):
    G: float
    C: float
    P: float
    R: float
    Gw: float
    S: float
    I: float

class TrendOut(BaseModel):
    trend: str
    canonical_name: str
    category: str
    trend_score: float
    current_score: float
    iran_relevance: float
    global_strength: float
    lifecycle: str
    confidence: float
    last_updated: str
    last_updated_jalali: str | None = None
    evidence_count: int
    supporting_sources: int
    seasonal_relevance: float | None = None
    growth: float | None = None
    is_actionable: bool
    explanation: str | None = None
    components: dict | None = None
    top_evidence: List[dict] | None = None

class SnapshotResponse(BaseModel):
    snapshot_time_utc: str
    snapshot_time_jalali: str | None = None
    season: str | None = None
    trends: List[TrendOut]
    meta: dict | None = None

class SourceOut(BaseModel):
    source_id: str
    name: str
    enabled: bool
    authority_weight: float
    update_frequency: str | None = None
    last_successful_fetch: str | None = None
    last_failed_fetch: str | None = None

class CollectionRunOut(BaseModel):
    id: int
    started_at: str
    finished_at: str | None = None
    sources_checked: int | None = None
    sources_successful: int | None = None
    new_documents: int | None = None
    status: str | None = None
