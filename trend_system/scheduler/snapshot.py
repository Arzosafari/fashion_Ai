"""Point-in-time trend snapshot materialization.

``materialize_snapshot`` is the single place where raw evidence is turned into
``Trend`` / ``TrendHistory`` / ``TrendEvidence`` / ``TrendSnapshot`` rows.

Correctness invariants (enforced by tests):

* Only signals with ``timestamp_utc <= snapshot_time`` are considered
  (SQL: ``WHERE timestamp_utc <= :snap``) — no future leakage.
* Synthetic seed documents are excluded from production scoring when
  ``exclude_synthetic=True`` (the default used by the collector).
* Snapshots and history are append-only; re-running the same snapshot time is
  idempotent and never duplicates evidence.
* Historical rows are never deleted by this function (except re-materializing
  the exact same snapshot timestamp).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, or_, select

from trend_system.aggregation.trend_aggregator import aggregate_trends
from trend_system.config import get_scoring_config
from trend_system.database.models import (
    FashionEntity,
    FashionObservation,
    RawDocument,
    Source,
    Trend,
    TrendEvidence,
    TrendHistory,
    TrendSignal,
    TrendSnapshot,
)
from trend_system.normalization.semantic_cluster import semantic_dedup_signals
from trend_system.utils.calendar import to_jalali_date_str, to_jalali_dict

logger = logging.getLogger(__name__)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = _aware(value)
    return aware.isoformat() if aware else None


async def _load_history(session, snapshot_time: datetime) -> dict[str, list[dict]]:
    """Last two history rows *before* ``snapshot_time`` per trend (for growth)."""
    rows = (
        await session.execute(
            select(
                TrendHistory.trend_id,
                TrendHistory.snapshot_time_utc,
                TrendHistory.current_score,
            )
            .where(TrendHistory.snapshot_time_utc < snapshot_time)
            .order_by(TrendHistory.trend_id, TrendHistory.snapshot_time_utc.desc())
        )
    ).all()
    history: dict[str, list[dict]] = {}
    for trend_id, snap_time, score in rows:
        bucket = history.setdefault(trend_id, [])
        if len(bucket) < 2:
            bucket.append(
                {
                    "snapshot_time_utc": _aware(snap_time),
                    "current_score": score,
                }
            )
    return history


async def _load_signals(
    session,
    snapshot_time: datetime,
    window_start: datetime,
    exclude_synthetic: bool,
) -> dict[str, list[dict]]:
    query = (
        select(
            TrendSignal.id.label("signal_id"),
            TrendSignal.concept,
            TrendSignal.source_id,
            TrendSignal.observation_id,
            TrendSignal.raw_document_id,
            TrendSignal.timestamp_utc,
            TrendSignal.confidence,
            TrendSignal.region,
            TrendSignal.evidence_type,
            TrendSignal.extracted_attributes,
            Source.authority_weight,
            Source.language.label("source_language"),
            RawDocument.title.label("doc_title"),
            RawDocument.is_synthetic,
            FashionObservation.category.label("observation_category"),
            FashionObservation.span_text,
            FashionEntity.category.label("entity_category"),
        )
        .join(Source, Source.source_id == TrendSignal.source_id, isouter=True)
        .join(RawDocument, RawDocument.id == TrendSignal.raw_document_id, isouter=True)
        .join(FashionObservation, FashionObservation.id == TrendSignal.observation_id, isouter=True)
        .join(FashionEntity, FashionEntity.canonical_name == TrendSignal.concept, isouter=True)
        # Point-in-time invariant: never read evidence newer than the snapshot.
        # Equivalent SQL: WHERE timestamp_utc <= :snap AND timestamp_utc >= :window_start
        .where(TrendSignal.timestamp_utc <= snapshot_time)
        .where(TrendSignal.timestamp_utc >= window_start)
    )
    if exclude_synthetic:
        query = query.where(
            or_(RawDocument.is_synthetic.is_(None), RawDocument.is_synthetic == False)  # noqa: E712
        )

    rows = (await session.execute(query)).all()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        ts = _aware(row.timestamp_utc)
        if ts is None:
            continue
        signal = {
            "signal_id": row.signal_id,
            "concept": row.concept,
            "source_id": row.source_id,
            "observation_id": row.observation_id,
            "raw_document_id": row.raw_document_id,
            "timestamp_utc": ts,
            "confidence": row.confidence,
            "region": row.region or "global",
            "language": row.source_language or "en",
            "evidence_type": row.evidence_type,
            "extracted_attributes": row.extracted_attributes,
            "authority_weight": row.authority_weight if row.authority_weight is not None else 0.5,
            "category": row.observation_category or row.entity_category or "unknown",
            "snippet": (row.doc_title or row.span_text or "").strip(),
        }
        grouped.setdefault(row.concept, []).append(signal)

    for signals in grouped.values():
        signals.sort(key=lambda s: s["timestamp_utc"])
    return grouped


def _payload_entry(trend: dict, window_days: float) -> dict[str, Any]:
    components = trend.get("components") or {}
    last_seen = trend["last_seen_utc"]
    source_ids = sorted({s.get("source_id") for s in trend.get("signals", []) if s.get("source_id")})
    return {
        "trend": trend["canonical_name"],
        "canonical_name": trend["canonical_name"],
        "category": trend.get("category", "unknown"),
        "trend_score": round(float(trend["current_score"]), 4),
        "current_score": round(float(trend["current_score"]), 4),
        "iran_relevance": components.get("I", 1.0),
        "global_strength": components.get("G", 0.0),
        "lifecycle": trend.get("lifecycle_state", "stable"),
        "confidence": components.get("R", 0.0),
        "last_updated": _iso(last_seen),
        "last_updated_jalali": to_jalali_date_str(_aware(last_seen)) if last_seen else None,
        "evidence_count": int(trend.get("evidence_count", 0)),
        "supporting_sources": int(trend.get("supporting_sources", 0)),
        "seasonal_relevance": components.get("S", 1.0),
        "growth": round(1.0 + float(trend.get("growth_rate", 0.0) or 0.0), 4),
        "is_actionable": bool(trend.get("is_actionable", False)),
        "explanation": trend.get("explanation", ""),
        "components": components,
        "trend_scope": "global",
        "source_ids": source_ids,
    }


async def materialize_snapshot(
    session,
    snapshot_time: datetime | None = None,
    exclude_synthetic: bool = False,
    scoring_cfg: dict | None = None,
    generated_by: str = "scheduler",
) -> list[dict]:
    """Aggregate evidence into the current trend snapshot and persist it."""
    now = _aware(snapshot_time) or datetime.now(timezone.utc)
    cfg = scoring_cfg or get_scoring_config()
    window_days = float(cfg.get("window_days", 30) or 30)
    window_start = now - timedelta(days=window_days)

    signals_by_concept = await _load_signals(session, now, window_start, exclude_synthetic)
    if not signals_by_concept:
        merged: dict[str, list[dict]] = {}
    else:
        merged = semantic_dedup_signals(signals_by_concept)

    history_map = await _load_history(session, now)
    trends = aggregate_trends(merged, now, cfg, history_map=history_map)

    # Attach raw signal lists for evidence reconstruction.
    for trend in trends:
        trend["signals"] = merged.get(trend["canonical_name"], [])

    trends.sort(key=lambda t: t["current_score"], reverse=True)
    payload = [_payload_entry(t, window_days) for t in trends]

    jalali = to_jalali_dict(now)
    season = jalali["season"]
    if (cfg.get("seasonal") or {}).get("calendar", "gregorian") != "persian":
        season = _gregorian_season(now.month)

    # Re-materializing the same timestamp must be idempotent.
    await session.execute(
        delete(TrendHistory).where(TrendHistory.snapshot_time_utc == now)
    )

    for trend in trends:
        canonical = trend["canonical_name"]
        category = trend.get("category") or "unknown"

        entity = await session.get(FashionEntity, canonical)
        if entity is None:
            entity = FashionEntity(
                canonical_name=canonical,
                category=category,
                aliases=[],
                global_relevance=None,
                scope="global",
                source_region="global",
            )
            session.add(entity)
            await session.flush()

        components = trend.get("components") or {}
        existing = await session.get(Trend, canonical)
        if existing is None:
            existing = Trend(
                canonical_name=canonical,
                category=category,
                first_seen_utc=trend["first_seen_utc"],
                last_seen_utc=trend["last_seen_utc"],
            )
            session.add(existing)
        else:
            # Preserve the true first-seen date across snapshots.
            if existing.first_seen_utc and _aware(existing.first_seen_utc) < trend["first_seen_utc"]:
                trend["first_seen_utc"] = _aware(existing.first_seen_utc)

        existing.category = category
        existing.global_score = components.get("G")
        existing.iran_relevance_score = components.get("I", 1.0)
        existing.recency_score = components.get("R")
        existing.growth_score = components.get("Gw")
        existing.cross_source_score = components.get("C")
        existing.seasonal_relevance = components.get("S")
        existing.current_score = trend["current_score"]
        existing.lifecycle_state = trend.get("lifecycle_state")
        existing.first_seen_utc = trend["first_seen_utc"]
        existing.first_seen_jalali = to_jalali_date_str(_aware(trend["first_seen_utc"]))
        existing.last_seen_utc = trend["last_seen_utc"]
        existing.last_seen_jalali = to_jalali_date_str(_aware(trend["last_seen_utc"]))
        existing.updated_at = now
        existing.evidence_count = trend.get("evidence_count", 0)
        existing.supporting_sources = trend.get("supporting_sources", 0)
        existing.is_actionable = bool(trend.get("is_actionable", False))
        existing.explanation = trend.get("explanation")
        existing.scoring_version = cfg.get("version", "v2_global")
        existing.trend_scope = "global"
        existing.source_region = "global"
        existing.semantic_consistency = components.get("semantic_consistency")
        existing.recurrence_score = components.get("recurrence")

        session.add(
            TrendHistory(
                trend_id=canonical,
                snapshot_time_utc=now,
                snapshot_time_jalali=jalali["jalali_date"],
                jalali_month=jalali["jalali_month"],
                season=season,
                global_score=components.get("G", 0.0) or 0.0,
                iran_relevance_score=components.get("I", 1.0) or 1.0,
                recency_score=components.get("R", 0.0) or 0.0,
                growth_score=components.get("Gw", 1.0) or 1.0,
                cross_source_score=components.get("C", 1.0) or 1.0,
                seasonal_relevance=components.get("S", 1.0) or 1.0,
                current_score=trend["current_score"],
                lifecycle_state=trend.get("lifecycle_state", "stable"),
                evidence_count=int(trend.get("evidence_count", 0)),
                supporting_sources=int(trend.get("supporting_sources", 0)),
                growth_rate=float(trend.get("growth_rate", 0.0) or 0.0),
                is_actionable=bool(trend.get("is_actionable", False)),
            )
        )

        # Evidence is idempotent per (trend, signal) pair.
        existing_signal_ids = set(
            (
                await session.execute(
                    select(TrendEvidence.signal_id).where(TrendEvidence.trend_id == canonical)
                )
            ).scalars().all()
        )
        for signal in trend["signals"]:
            signal_id = signal.get("signal_id")
            if signal_id is not None and signal_id in existing_signal_ids:
                continue
            snippet = (signal.get("snippet") or "").strip()
            if len(snippet) < 5:
                snippet = f"Evidence from {signal.get('source_id', 'unknown source')}"
            session.add(
                TrendEvidence(
                    trend_id=canonical,
                    source_id=signal.get("source_id"),
                    observation_id=signal.get("observation_id"),
                    signal_id=signal_id,
                    raw_document_id=signal.get("raw_document_id"),
                    evidence_type=signal.get("evidence_type") or "article",
                    confidence=signal.get("confidence"),
                    timestamp_utc=signal["timestamp_utc"],
                    timestamp_jalali=to_jalali_date_str(_aware(signal["timestamp_utc"])),
                    snippet=snippet[:1000],
                )
            )
        await session.flush()

    # Upsert snapshot for this timestamp.
    existing_snapshot = await session.get(TrendSnapshot, now)
    if existing_snapshot is None:
        existing_snapshot = TrendSnapshot(
            snapshot_time_utc=now,
            snapshot_time_jalali=jalali["jalali_date"],
            season=season,
            trends=payload,
            top_trends_count=len(payload),
            generated_by=generated_by,
            scoring_version=cfg.get("version", "v2_global"),
            scoring_mode=cfg.get("scoring_mode", "gated_geom"),
            meta={
                "window_days": int(window_days),
                "sources": len(payload),
                "exclude_synthetic": bool(exclude_synthetic),
            },
        )
        session.add(existing_snapshot)
    else:
        existing_snapshot.snapshot_time_jalali = jalali["jalali_date"]
        existing_snapshot.season = season
        existing_snapshot.trends = payload
        existing_snapshot.top_trends_count = len(payload)
        existing_snapshot.generated_by = generated_by
        existing_snapshot.scoring_version = cfg.get("version", "v2_global")
        existing_snapshot.scoring_mode = cfg.get("scoring_mode", "gated_geom")
        existing_snapshot.meta = {
            "window_days": int(window_days),
            "sources": len(payload),
            "exclude_synthetic": bool(exclude_synthetic),
        }

    await session.commit()
    logger.info(
        "Materialized trend snapshot at %s with %d trends (exclude_synthetic=%s)",
        now.isoformat(),
        len(payload),
        exclude_synthetic,
    )
    return payload


def _gregorian_season(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"
