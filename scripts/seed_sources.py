"""Seed sources, taxonomy, seasonal affinity"""
import asyncio
from trend_system.main import lifespan
from trend_system.database.session import get_async_sessionmaker, init_db
from sqlalchemy import select
from trend_system.database.models import Source, FashionEntity, SeasonalAffinity
from trend_system.config import get_sources_config, get_taxonomy_config, get_seasonal_config

async def main():
    await init_db()
    async with get_async_sessionmaker()() as session:
        # sources
        result = await session.execute(select(Source))
        if not result.scalars().first():
            for src in get_sources_config().get("sources",[]):
                session.add(Source(
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
                    enabled=src.get("enabled",False),
                    robots_status=src.get("robots_status"),
                    sitemap_url=src.get("sitemap_url"),
                    rss_url=src.get("rss_url"),
                ))
            await session.commit()
            print("sources seeded")
        # taxonomy
        result = await session.execute(select(FashionEntity))
        if not result.scalars().first():
            for ent in get_taxonomy_config().get("entities",[]):
                session.add(FashionEntity(
                    canonical_name=ent["canonical"],
                    category=ent["category"],
                    aliases=ent.get("aliases",[]),
                    iran_compatibility=ent.get("iran_compatibility",0.7),
                    ideal_temp_range=ent.get("ideal_temp_range"),
                ))
            await session.commit()
            print("taxonomy seeded")
        # seasonal
        result = await session.execute(select(SeasonalAffinity))
        if not result.scalars().first():
            affs = get_seasonal_config().get("affinities",{})
            for canon, seasons in affs.items():
                for season, aff in seasons.items():
                    session.add(SeasonalAffinity(canonical_name=canon, season=season, affinity=aff))
            await session.commit()
            print("seasonal seeded")
        print("done")

if __name__ == "__main__":
    asyncio.run(main())
