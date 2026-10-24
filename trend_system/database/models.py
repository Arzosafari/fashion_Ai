from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, Text, Boolean, Float, DateTime, JSON, Index, ForeignKey, String
)
from sqlalchemy.orm import declarative_base
# JSON is used instead of PostgreSQL JSONB so the schema stays portable to SQLite.
# (An optional deployment may still use PostgreSQL via DATABASE_URL.)

Base = declarative_base()

# Use TIMESTAMPTZ for UTC; store jalali as TEXT for display.

class Source(Base):
    __tablename__ = "sources"
    source_id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)
    country = Column(String(2), nullable=True)
    region = Column(Text, nullable=False)
    language = Column(Text, nullable=False)
    authority_weight = Column(Float, nullable=False)
    freshness_weight = Column(Float, nullable=False)
    accessibility = Column(Text, nullable=True)
    extraction_method = Column(Text, nullable=True)
    update_frequency = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    robots_status = Column(Text, nullable=True)
    sitemap_url = Column(Text, nullable=True)
    rss_url = Column(Text, nullable=True)
    # Global migration: scope/source_region for isolating Iranian history
    scope = Column(Text, nullable=True, default="global")  # global | iranian | archived
    source_region = Column(Text, nullable=True, default="global")
    last_successful_fetch = Column(DateTime(timezone=True), nullable=True)
    last_failed_fetch = Column(DateTime(timezone=True), nullable=True)
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RawDocument(Base):
    __tablename__ = "raw_documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Text, ForeignKey("sources.source_id"), nullable=False)
    source_url = Column(Text, unique=True, nullable=False)
    canonical_url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    content_html = Column(Text, nullable=True)
    content_text = Column(Text, nullable=False)
    publication_date_utc = Column(DateTime(timezone=True), nullable=True)
    publication_date_jalali = Column(Text, nullable=True)
    publication_season = Column(Text, nullable=True)
    publication_jalali_month = Column(Integer, nullable=True)
    publication_gregorian_month = Column(Integer, nullable=True)
    collection_date_utc = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    language = Column(Text, nullable=True)
    author = Column(Text, nullable=True)
    category = Column(Text, nullable=True)
    image_urls = Column(JSON, nullable=True)
    meta = Column("metadata", JSON, nullable=True)
    content_hash = Column(String(64), nullable=False)
    extraction_timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_duplicate = Column(Boolean, default=False)
    duplicate_of = Column(Integer, ForeignKey("raw_documents.id"), nullable=True)
    is_synthetic = Column(Boolean, default=False)

    __table_args__ = (
        Index("idx_raw_pub", "source_id", "publication_date_utc"),
        Index("idx_raw_hash", "content_hash"),
        Index("idx_raw_collection", "collection_date_utc"),
    )


class FashionEntity(Base):
    __tablename__ = "fashion_entities"
    canonical_name = Column(Text, primary_key=True)
    category = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    aliases = Column(JSON, nullable=True)
    embedding = Column(JSON, nullable=True)  # store as JSON if pgvector not available; optional
    iran_compatibility = Column(Float, nullable=True)
    global_relevance = Column(Float, nullable=True)
    scope = Column(Text, nullable=True, default="global")  # global | iranian for isolation
    source_region = Column(Text, nullable=True)
    ideal_temp_range = Column(JSON, nullable=True)
    parent_id = Column(Text, nullable=True)


class LLMCache(Base):
    __tablename__ = "llm_cache"
    cache_key = Column(String(64), primary_key=True)
    prompt_version = Column(Text, nullable=False)
    provider_model = Column(Text, nullable=False)
    input_hash = Column(String(64), nullable=False)
    output_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    hit_count = Column(Integer, default=1)

    __table_args__ = (Index("idx_llm_input", "input_hash"),)


class FashionObservation(Base):
    __tablename__ = "fashion_observations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_document_id = Column(Integer, ForeignKey("raw_documents.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(Text, ForeignKey("sources.source_id"), nullable=False)
    entity_id = Column(Text, ForeignKey("fashion_entities.canonical_name"), nullable=True)
    raw_term = Column(Text, nullable=False)
    canonical_name = Column(Text, nullable=True)
    category = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    extractor_type = Column(Text, nullable=False)
    span_text = Column(Text, nullable=True)
    attributes = Column(JSON, nullable=True)
    observed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    region = Column(Text, default="global")
    llm_cache_key = Column(String(64), ForeignKey("llm_cache.cache_key"), nullable=True)


class TrendSignal(Base):
    __tablename__ = "trend_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    concept = Column(Text, ForeignKey("fashion_entities.canonical_name"), nullable=False)
    source_id = Column(Text, ForeignKey("sources.source_id"), nullable=False)
    observation_id = Column(Integer, ForeignKey("fashion_observations.id"), nullable=True)
    raw_document_id = Column(Integer, ForeignKey("raw_documents.id"), nullable=False)
    timestamp_utc = Column(DateTime(timezone=True), nullable=False)
    timestamp_jalali = Column(Text, nullable=True)
    jalali_month = Column(Integer, nullable=True)
    season = Column(Text, nullable=True)
    evidence_type = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    region = Column(Text, nullable=True)
    extracted_attributes = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_signal_concept_time", "concept", "timestamp_utc"),
        Index("idx_signal_region", "region"),
    )


class Trend(Base):
    __tablename__ = "trends"
    canonical_name = Column(Text, ForeignKey("fashion_entities.canonical_name"), primary_key=True)
    category = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    global_score = Column(Float, nullable=True)
    iran_relevance_score = Column(Float, nullable=True)
    recency_score = Column(Float, nullable=True)
    growth_score = Column(Float, nullable=True)
    cross_source_score = Column(Float, nullable=True)
    seasonal_relevance = Column(Float, nullable=True)
    current_score = Column(Float, nullable=True)
    lifecycle_state = Column(Text, nullable=True)
    first_seen_utc = Column(DateTime(timezone=True), nullable=False)
    first_seen_jalali = Column(Text, nullable=True)
    last_seen_utc = Column(DateTime(timezone=True), nullable=False)
    last_seen_jalali = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    evidence_count = Column(Integer, default=0)
    supporting_sources = Column(Integer, default=0)
    is_actionable = Column(Boolean, default=False)
    recommendation_payload = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    scoring_version = Column(Text, default="v2_global")
    # Global isolation
    trend_scope = Column(Text, nullable=True, default="global")  # global | iranian (archived)
    source_region = Column(Text, nullable=True, default="global")
    semantic_consistency = Column(Float, nullable=True)
    recurrence_score = Column(Float, nullable=True)

    __table_args__ = (
        Index("idx_trends_score", "current_score"),
        Index("idx_trends_lifecycle", "lifecycle_state"),
        Index("idx_trends_category", "category"),
    )


class TrendEvidence(Base):
    __tablename__ = "trend_evidence"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trend_id = Column(Text, ForeignKey("trends.canonical_name", ondelete="CASCADE"), nullable=False)
    source_id = Column(Text, ForeignKey("sources.source_id"), nullable=False)
    observation_id = Column(Integer, ForeignKey("fashion_observations.id"), nullable=True)
    signal_id = Column(Integer, ForeignKey("trend_signals.id"), nullable=True)
    raw_document_id = Column(Integer, ForeignKey("raw_documents.id"), nullable=False)
    evidence_type = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    timestamp_utc = Column(DateTime(timezone=True), nullable=False)
    timestamp_jalali = Column(Text, nullable=True)
    snippet = Column(Text, nullable=True)

    __table_args__ = (Index("idx_evidence_trend_time", "trend_id", "timestamp_utc"),)


class TrendHistory(Base):
    __tablename__ = "trend_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trend_id = Column(Text, ForeignKey("trends.canonical_name", ondelete="CASCADE"), nullable=False)
    snapshot_time_utc = Column(DateTime(timezone=True), nullable=False)
    snapshot_time_jalali = Column(Text, nullable=True)
    jalali_month = Column(Integer, nullable=True)
    season = Column(Text, nullable=True)
    global_score = Column(Float, nullable=False)
    iran_relevance_score = Column(Float, nullable=False)
    recency_score = Column(Float, nullable=False)
    growth_score = Column(Float, nullable=False)
    cross_source_score = Column(Float, nullable=False)
    seasonal_relevance = Column(Float, nullable=False)
    current_score = Column(Float, nullable=False)
    lifecycle_state = Column(Text, nullable=False)
    evidence_count = Column(Integer, nullable=False)
    supporting_sources = Column(Integer, nullable=False)
    growth_rate = Column(Float, nullable=True)
    is_actionable = Column(Boolean, nullable=False)

    __table_args__ = (
        Index("idx_history_trend_time", "trend_id", "snapshot_time_utc"),
        Index("idx_history_snapshot", "snapshot_time_utc"),
    )


class TrendSnapshot(Base):
    __tablename__ = "trend_snapshots"
    snapshot_time_utc = Column(DateTime(timezone=True), primary_key=True)
    snapshot_time_jalali = Column(Text, nullable=True)
    season = Column(Text, nullable=True)
    trends = Column(JSON, nullable=False)
    top_trends_count = Column(Integer, nullable=False)
    generated_by = Column(Text, default="scheduler")
    scoring_version = Column(Text, nullable=False)
    scoring_mode = Column(Text, nullable=False)
    meta = Column(JSON, nullable=True)

    __table_args__ = (Index("idx_snap_time", "snapshot_time_utc"),)


class SeasonalAffinity(Base):
    __tablename__ = "seasonal_affinity"
    canonical_name = Column(Text, ForeignKey("fashion_entities.canonical_name"), primary_key=True)
    season = Column(Text, primary_key=True)
    affinity = Column(Float, nullable=False)


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime(timezone=True), nullable=True)
    sources_checked = Column(Integer, nullable=True)
    sources_successful = Column(Integer, nullable=True)
    sources_failed = Column(Integer, nullable=True)
    new_documents = Column(Integer, nullable=True)
    duplicates = Column(Integer, nullable=True)
    fashion_signals = Column(Integer, nullable=True)
    trends_created = Column(Integer, nullable=True)
    trends_updated = Column(Integer, nullable=True)
    status = Column(Text, nullable=True)
    error_log = Column(JSON, nullable=True)


class SourceHealth(Base):
    __tablename__ = "source_health"
    source_id = Column(Text, ForeignKey("sources.source_id"), primary_key=True)
    consecutive_failures = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_success = Column(DateTime(timezone=True), nullable=True)
    is_healthy = Column(Boolean, default=True)
    circuit_open_until = Column(DateTime(timezone=True), nullable=True)
