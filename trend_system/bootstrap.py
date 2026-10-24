"""Idempotent bootstrap for the trend module.

Called from the API startup hook and from the standalone trend app.  It only
creates missing tables/columns and seeds reference data when the tables are
empty — existing trend data is never modified or deleted.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from trend_system.config import get_seasonal_config, get_sources_config, get_taxonomy_config
from trend_system.database.models import (
    FashionEntity,
    SeasonalAffinity,
    Source,
    TrendSnapshot,
)
from trend_system.database.session import get_async_sessionmaker, init_db

logger = logging.getLogger(__name__)

_BOOTSTRAPPED_URLS: set[str] = set()


def _source_kwargs(src: dict) -> dict:
    return {
        "source_id": src["source_id"],
        "name": src.get("name", src["source_id"]),
        "source_type": src.get("source_type", "editorial"),
        "country": src.get("country"),
        "region": src.get("region", "global"),
        "language": src.get("language", "en"),
        "authority_weight": src.get("authority_weight", 0.5),
        "freshness_weight": src.get("freshness_weight", 0.5),
        "accessibility": src.get("accessibility"),
        "extraction_method": src.get("extraction_method"),
        "update_frequency": src.get("update_frequency"),
        "enabled": src.get("enabled", False),
        "robots_status": src.get("robots_status"),
        "sitemap_url": src.get("sitemap_url"),
        "rss_url": src.get("rss_url"),
        "scope": src.get("scope", "global"),
        "source_region": src.get("region", "global"),
    }


async def seed_reference_data(session, force: bool = False) -> dict:
    """Seed sources / taxonomy / seasonal affinity when missing."""
    counts = {"sources": 0, "entities": 0, "seasonal": 0}

    existing_sources = (await session.execute(select(Source))).scalars().all()
    known = {s.source_id: s for s in existing_sources}
    for src in (get_sources_config() or {}).get("sources", []):
        if not src.get("source_id"):
            continue
        if src["source_id"] in known:
            # Keep historical rows intact; only refresh enablement/metadata when forced.
            if force:
                for key, value in _source_kwargs(src).items():
                    setattr(known[src["source_id"]], key, value)
            continue
        session.add(Source(**_source_kwargs(src)))
        counts["sources"] += 1

    existing_entities = (await session.execute(select(FashionEntity))).scalars().all()
    known_entities = {e.canonical_name for e in existing_entities}
    for ent in (get_taxonomy_config() or {}).get("entities", []):
        canonical = ent.get("canonical")
        if not canonical or canonical in known_entities:
            continue
        session.add(
            FashionEntity(
                canonical_name=canonical,
                category=ent.get("category", "unknown"),
                aliases=ent.get("aliases", []),
                iran_compatibility=ent.get("iran_compatibility"),
                global_relevance=ent.get("global_relevance"),
                scope="global",
                source_region="global",
                ideal_temp_range=ent.get("ideal_temp_range"),
            )
        )
        counts["entities"] += 1

    has_seasonal = (await session.execute(select(SeasonalAffinity).limit(1))).scalars().first()
    if has_seasonal is None:
        for canonical, seasons in ((get_seasonal_config() or {}).get("affinities") or {}).items():
            for season, affinity in (seasons or {}).items():
                session.add(
                    SeasonalAffinity(
                        canonical_name=canonical, season=season, affinity=float(affinity)
                    )
                )
                counts["seasonal"] += 1

    await session.commit()
    return counts


async def bootstrap_trend_module(force_seed: bool = False) -> dict:
    """Initialise schema + seed reference data once per process."""
    from trend_system.database.session import get_database_url

    cache_key = get_database_url()
    if cache_key in _BOOTSTRAPPED_URLS and not force_seed:
        return {"status": "already_initialized"}

    await init_db()
    async with get_async_sessionmaker()() as session:
        seeded = await seed_reference_data(session, force=force_seed)
        snapshot = (
            await session.execute(select(TrendSnapshot).order_by(TrendSnapshot.snapshot_time_utc.desc()).limit(1))
        ).scalars().first()
    _BOOTSTRAPPED_URLS.add(cache_key)
    info = {
        "status": "initialized",
        "seeded": seeded,
        "latest_snapshot": snapshot.snapshot_time_utc.isoformat() if snapshot else None,
    }
    logger.info("Trend module bootstrap: %s", info)
    return info


def reset_bootstrap_flag() -> None:
    global _BOOTSTRAPPED
    _BOOTSTRAPPED_URLS: set[str] = set()
