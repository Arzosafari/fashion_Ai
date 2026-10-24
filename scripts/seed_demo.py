"""Seed demo trends without needing live scraping — inserts synthetic raw_documents, observations, signals and materializes snapshot"""
import asyncio
from datetime import datetime, timezone, timedelta
import hashlib

from trend_system.database.session import get_async_sessionmaker, init_db
from trend_system.database.models import RawDocument, FashionObservation, TrendSignal, Source, FashionEntity
from trend_system.utils.calendar import to_jalali_dict
from trend_system.scheduler.snapshot import materialize_snapshot
from trend_system.config import get_sources_config, get_taxonomy_config
from sqlalchemy import select

async def main():
    await init_db()
    async with get_async_sessionmaker()() as session:
        # ensure sources and entities exist
        result = await session.execute(select(Source))
        if not result.scalars().first():
            for src in get_sources_config().get("sources", []):
                session.add(Source(
                    source_id=src["source_id"],
                    name=src["name"],
                    source_type=src.get("source_type","magazine"),
                    country=src.get("country"),
                    region=src.get("region","global"),
                    language=src.get("language","en"),
                    authority_weight=src.get("authority_weight",0.5),
                    freshness_weight=src.get("freshness_weight",0.5),
                    enabled=src.get("enabled",False),
                ))
            await session.commit()
        result = await session.execute(select(FashionEntity))
        if not result.scalars().first():
            for ent in get_taxonomy_config().get("entities", []):
                session.add(FashionEntity(
                    canonical_name=ent["canonical"],
                    category=ent["category"],
                    aliases=ent.get("aliases",[]),
                    iran_compatibility=ent.get("iran_compatibility",0.7),
                    ideal_temp_range=ent.get("ideal_temp_range"),
                ))
            await session.commit()

        # Create synthetic raw documents for 4 sources, 3 concepts
        concepts = [
            ("wide_leg_bottom", "silhouette", "شلوار گشاد ترند امسال", "Wide leg trousers are taking over Tehran street style. Manteau with wide leg pants is everywhere.", "fa"),
            ("manteau", "garment", "مانتو کتی ترند", "Manteau remains essential for Iranian style, now with wide leg bottom.", "fa"),
            ("linen", "material", "Linen for summer", "Linen dominates summer collections in global and Iranian magazines", "en"),
            ("oversized_style", "style", "استایل اورسایز", "Oversized style is rising across Vogue and BaniMag", "fa"),
        ]
        sources = ["vogue","digikala_mag","banimode_mag","modeworld"]
        now = datetime.now(timezone.utc)
        for idx, (canon, cat, title_fa, text_fa, lang) in enumerate(concepts):
            for sidx, src in enumerate(sources):
                # For each concept, create signals from 3 IR sources + 1 global with staggered dates
                # This ensures cross-source evidence
                pub = now - timedelta(days=sidx*2 + idx)
                jalali = to_jalali_dict(pub)
                content = f"{title_fa} {text_fa} {canon}"
                h = hashlib.sha256(content.encode()).hexdigest()
                url = f"https://example.com/{src}/{canon}/{idx}/{sidx}"
                # Check if exists
                existing = await session.execute(select(RawDocument).where(RawDocument.source_url==url))
                if existing.scalars().first():
                    continue
                doc = RawDocument(
                    source_id=src,
                    source_url=url,
                    title=title_fa,
                    content_html=f"<html><body>{content}</body></html>",
                    content_text=content,
                    publication_date_utc=pub,
                    publication_date_jalali=jalali["jalali_date"],
                    publication_season=jalali["season"],
                    publication_jalali_month=jalali["jalali_month"],
                    publication_gregorian_month=pub.month,
                    collection_date_utc=now,
                    language=lang,
                    author="demo",
                    category="fashion",
                    image_urls=[],
                    meta={"is_synthetic": True},
                    content_hash=h,
                    is_synthetic=True,
                )
                session.add(doc)
                await session.flush()
                # observation
                obs = FashionObservation(
                    raw_document_id=doc.id,
                    source_id=src,
                    entity_id=canon,
                    raw_term=canon,
                    canonical_name=canon,
                    category=cat,
                    confidence=0.85,
                    extractor_type="rule",
                    span_text=content[:100],
                    observed_at=pub,
                    region="iranian" if src in ["digikala_mag","banimode_mag","modeworld"] else "global",
                )
                session.add(obs)
                await session.flush()
                # signal
                sig = TrendSignal(
                    concept=canon,
                    source_id=src,
                    observation_id=obs.id,
                    raw_document_id=doc.id,
                    timestamp_utc=pub,
                    timestamp_jalali=jalali["jalali_date"],
                    jalali_month=jalali["jalali_month"],
                    season=jalali["season"],
                    evidence_type="article",
                    confidence=0.85,
                    region="iranian" if src in ["digikala_mag","banimode_mag","modeworld"] else "global",
                )
                session.add(sig)
        await session.commit()
        print("synthetic docs/signals inserted")

        # materialize snapshot
        snap = await materialize_snapshot(session, now)
        print(f"snapshot materialized with {len(snap)} trends")
        for t in snap:
            print(f" - {t['trend']}: score={t['trend_score']:.3f} I={t['iran_relevance']:.2f} lifecycle={t['lifecycle']} ev={t['evidence_count']}")

if __name__ == "__main__":
    asyncio.run(main())
