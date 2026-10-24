from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from typing import List

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


# ---------------------------------------------------------------------------
# Documented contracts for the integrated API (Fashion AI ↔ Trend Module)
# ---------------------------------------------------------------------------

class TrendItemOut(BaseModel):
    """One materialized trend inside a snapshot (extra fields preserved)."""
    model_config = ConfigDict(extra="allow")

    trend: str | None = None
    canonical_name: str | None = None
    category: str | None = None
    trend_score: float | None = None
    current_score: float | None = None
    iran_relevance: float | None = Field(default=None, description="Always 1.0 for the global pipeline (neutral gate).")
    global_strength: float | None = None
    lifecycle: str | None = None
    confidence: float | None = Field(default=None, description="Recency-weighted freshness score R.")
    last_updated: str | None = None
    last_updated_jalali: str | None = None
    evidence_count: int | None = None
    supporting_sources: int | None = None
    seasonal_relevance: float | None = None
    growth: float | None = None
    is_actionable: bool | None = None
    explanation: str | None = None
    components: dict | None = None


class TrendsSnapshotResponse(BaseModel):
    snapshot_time_utc: str | None = None
    snapshot_time_jalali: str | None = None
    season: str | None = None
    trends: List[TrendItemOut] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class TrendsForRecommendationResponse(BaseModel):
    snapshot_time_utc: str | None = None
    snapshot_time_jalali: str | None = None
    season: str | None = None
    trends: List[TrendItemOut] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class TrendContextItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    canonical_name: str | None = None
    category: str | None = None
    trend_score: float | None = None
    lifecycle: str | None = None
    supporting_sources: int | None = None
    evidence_count: int | None = None
    is_actionable: bool | None = None
    seasonal_relevance: float | None = None
    explanation: str | None = None


class TrendContextResponse(BaseModel):
    """Compact global-trend context consumed by the request/recommendation layer."""
    available: bool
    status: str = Field(description="ok | no_snapshot | unavailable")
    message: str | None = None
    snapshot_time_utc: str | None = None
    season: str | None = None
    trends: List[TrendContextItem] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
