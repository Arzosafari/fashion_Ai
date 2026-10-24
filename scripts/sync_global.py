#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trend_system.database.session import get_async_sessionmaker, init_db
from sqlalchemy import select
from trend_system.config import get_sources_config, get_taxonomy_config, get_seasonal_config
from trend_system.database.models import Source, FashionEntity, SeasonalAffinity

async def sync_sources():
    await init_db()
    cfg = get_sources_config()
    async with get_async_sessionmaker()() as session:
        for src in cfg.get("sources", []):
            existing = await session.get(Source, src["source_id"])
            if existing:
                # update fields
                existing.name = src["name"]
                existing.source_type = src.get("source_type", existing.source_type)
                existing.country = src.get("country", existing.country)
                existing.region = src.get("region", "global")
                existing.language = src.get("language", "en")
                existing.authority_weight = src.get("authority_weight", existing.authority_weight)
                existing.freshness_weight = src.get("freshness_weight", existing.freshness_weight)
                existing.accessibility = src.get("accessibility", existing.accessibility)
                existing.extraction_method = src.get("extraction_method", existing.extraction_method)
                existing.update_frequency = src.get("update_frequency", existing.update_frequency)
                existing.enabled = src.get("enabled", False)
                existing.robots_status = src.get("robots_status", existing.robots_status)
                existing.sitemap_url = src.get("sitemap_url", existing.sitemap_url)
                existing.rss_url = src.get("rss_url", existing.rss_url)
                if hasattr(existing, "scope"):
                    existing.scope = src.get("scope", "global")
                    existing.source_region = src.get("region", "global")
                print(f"updated source {src['source_id']} enabled={src.get('enabled')} scope={src.get('scope')}")
            else:
                s = Source(
                    source_id=src["source_id"],
                    name=src["name"],
                    source_type=src.get("source_type","magazine"),
                    country=src.get("country"),
                    region=src.get("region","global"),
                    language=src.get("language","en"),
                    authority_weight=src.get("authority_weight",0.5),
                    freshness_weight=src.get("freshness_weight",0.5),
                    accessibility=src.get("accessibility","public"),
                    extraction_method=src.get("extraction_method"),
                    update_frequency=src.get("update_frequency"),
                    enabled=src.get("enabled", False),
                    robots_status=src.get("robots_status"),
                    sitemap_url=src.get("sitemap_url"),
                    rss_url=src.get("rss_url"),
                )
                if hasattr(s, "scope"):
                    s.scope = src.get("scope","global")
                    s.source_region = src.get("region","global")
                session.add(s)
                print(f"added source {src['source_id']}")
        await session.commit()
        # report
        res = await session.execute(select(Source))
        rows = res.scalars().all()
        print(f"Total sources: {len(rows)}")
        for r in rows:
            print(f" - {r.source_id} enabled={r.enabled} scope={getattr(r,'scope', 'N/A')} sitemap={r.sitemap_url}")

async def sync_taxonomy():
    await init_db()
    cfg = get_taxonomy_config()
    async with get_async_sessionmaker()() as session:
        for ent in cfg.get("entities", []):
            canon = ent["canonical"]
            existing = await session.get(FashionEntity, canon)
            if existing:
                existing.category = ent["category"]
                existing.aliases = ent.get("aliases", [])
                existing.iran_compatibility = ent.get("iran_compatibility", ent.get("global_relevance", 0.7))
                if hasattr(existing, "global_relevance"):
                    existing.global_relevance = ent.get("global_relevance", ent.get("iran_compatibility", 0.7))
                    existing.scope = ent.get("scope", "global")
                existing.ideal_temp_range = ent.get("ideal_temp_range")
                print(f"updated entity {canon}")
            else:
                fe = FashionEntity(
                    canonical_name=ent["canonical"],
                    category=ent["category"],
                    aliases=ent.get("aliases", []),
                    iran_compatibility=ent.get("iran_compatibility", ent.get("global_relevance", 0.7)),
                    ideal_temp_range=ent.get("ideal_temp_range"),
                )
                if hasattr(fe, "global_relevance"):
                    fe.global_relevance = ent.get("global_relevance", ent.get("iran_compatibility", 0.7))
                    fe.scope = "global"
                session.add(fe)
                print(f"added entity {canon}")
        await session.commit()
        # seasonal
        await session.execute(select(SeasonalAffinity).limit(1))
        # Clear and reseed seasonal_affinity
        from sqlalchemy import delete
        await session.execute(delete(SeasonalAffinity))
        affs = get_seasonal_config().get("affinities", {})
        for canon, seasons in affs.items():
            for season, aff in seasons.items():
                session.add(SeasonalAffinity(canonical_name=canon, season=season, affinity=aff))
        await session.commit()
        print("seasonal affinity seeded")

async def main():
    await sync_sources()
    await sync_taxonomy()

if __name__ == "__main__":
    asyncio.run(main())
