"""Live collector → ingestion → snapshot end-to-end (SAFE limit)"""
import asyncio
import os
import time
import logging
from datetime import datetime, timezone
from collections import defaultdict

import httpx
from sqlalchemy import select

from trend_system.collectors.registry import get_enabled_collectors
from trend_system.utils.http import get_http_client
from trend_system.utils.robots import fetch_robots_txt, is_allowed_by_robots
from trend_system.database.session import get_async_sessionmaker, init_db
from trend_system.database.models import CollectionRun, SourceHealth, Source, RawDocument, FashionObservation, TrendSignal, Trend, TrendSnapshot
from trend_system.ingestion.pipeline import ingest_url
from trend_system.scheduler.snapshot import materialize_snapshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("live-collector")

MAX_URLS_PER_SOURCE = int(os.getenv("MAX_URLS_PER_SOURCE", "5"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "2.0"))
TIMEOUT = 15
# Validation mode: when 1, snapshot excludes synthetic seed data so synthetic cannot inflate cross-source agreement.
# Production must be 1; unit tests explicitly pass include_synthetic=True to snapshot.
EXCLUDE_SYNTHETIC_DEFAULT = os.getenv("EXCLUDE_SYNTHETIC", "1") == "1"

async def live_run(limit_per_source: int = MAX_URLS_PER_SOURCE, exclude_synthetic: bool = EXCLUDE_SYNTHETIC_DEFAULT):
    await init_db()
    print(f"=== LIVE COLLECTOR → INGESTION → SNAPSHOT (limit {limit_per_source} per source, exclude_synthetic={exclude_synthetic}) ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Rate limit: {RATE_LIMIT_DELAY}s between fetches, timeout {TIMEOUT}s, 3x retry in fetch_document")

    async with get_async_sessionmaker()() as session:
        # Ensure sources seeded (if empty)
        result = await session.execute(select(Source))
        rows = result.scalars().all()
        if not rows:
            from trend_system.config import get_sources_config
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
                    sitemap_url=src.get("sitemap_url"),
                    rss_url=src.get("rss_url"),
                ))
            await session.commit()

    # Start collection_run record
    start_time = datetime.now(timezone.utc)
    collection_run = CollectionRun(
        started_at=start_time,
        sources_checked=0,
        sources_successful=0,
        sources_failed=0,
        new_documents=0,
        duplicates=0,
        fashion_signals=0,
        status="running",
        error_log={},
    )
    async with get_async_sessionmaker()() as session:
        session.add(collection_run)
        await session.commit()
        await session.refresh(collection_run)
        run_id = collection_run.id

    total_new_docs = 0
    total_duplicates = 0
    total_signals = 0
    per_source_stats = []
    failed_sources = []
    successful_sources = []

    async with get_http_client() as http_client:
        http_client.timeout = httpx.Timeout(TIMEOUT)
        collectors = get_enabled_collectors(http_client)
        print(f"Enabled collectors: {[c.source_id for c in collectors]} (total {len(collectors)})")
        async with get_async_sessionmaker()() as session:
            cr = await session.get(CollectionRun, run_id)
            cr.sources_checked = len(collectors)
            await session.commit()

        for coll in collectors:
            sid = coll.source_id
            print(f"\n--- Source: {sid} ---")
            stat = {"source_id": sid, "discovered":0, "checked":0, "successful":0, "failed":0, "ingested":0, "duplicates":0, "errors":[]}
            try:
                # Discover URLs — any sitemap/network failure now raises and is recorded (fix #1)
                try:
                    urls = await coll.discover_urls(http_client)
                    stat["discovered"] = len(urls)
                    print(f"  Discovered {len(urls)} URLs")
                    if len(urls) == 0:
                        # Zero without exception is legitimate empty sitemap — just warn, not failure
                        print(f"  WARNING: 0 URLs discovered for {sid} (sitemap empty but reachable)")
                except Exception as e:
                    print(f"  [ERROR] discover failed: {e}")
                    stat["errors"].append(f"discover: {e}")
                    failed_sources.append(sid)
                    # update source_health with consecutive failures
                    async with get_async_sessionmaker()() as s2:
                        health = await s2.get(SourceHealth, sid)
                        if not health:
                            health = SourceHealth(source_id=sid, consecutive_failures=1, last_error=str(e), is_healthy=False)
                            s2.add(health)
                        else:
                            health.consecutive_failures = (health.consecutive_failures or 0) + 1
                            health.last_error = str(e)[:500]
                            health.is_healthy = False
                        # update sources failure count
                        src_row = await s2.get(Source, sid)
                        if src_row:
                            src_row.failure_count = (src_row.failure_count or 0) + 1
                            src_row.last_failed_fetch = datetime.now(timezone.utc)
                        await s2.commit()
                    per_source_stats.append(stat)
                    continue

                urls_limited = urls[:limit_per_source]
                print(f"  Limited to {len(urls_limited)} URLs (SAFE TEST)")
                for idx, url in enumerate(urls_limited):
                    stat["checked"] += 1
                    try:
                        robots_content = await fetch_robots_txt(url, http_client)
                        if robots_content and not is_allowed_by_robots(url, robots_content=robots_content):
                            print(f"    [{idx+1}/{len(urls_limited)}] SKIP robots disallow: {url}")
                            stat["failed"] += 1
                            stat["errors"].append(f"robots disallow: {url}")
                            continue
                    except Exception as e:
                        print(f"    robots check error for {url}: {e} — proceeding")

                    try:
                        res = await coll.fetch_document(url, http_client)
                    except Exception as e:
                        print(f"    [{idx+1}/{len(urls_limited)}] FETCH ERROR {url}: {e}")
                        stat["failed"] += 1
                        stat["errors"].append(f"fetch error {url}: {e}")
                        continue

                    if res.status != 200 or not res.content:
                        print(f"    [{idx+1}/{len(urls_limited)}] HTTP {res.status} fail {url}: {res.error}")
                        stat["failed"] += 1
                        stat["errors"].append(f"http {res.status} {url}: {res.error}")
                        await asyncio.sleep(RATE_LIMIT_DELAY)
                        continue

                    try:
                        async with get_async_sessionmaker()() as sess:
                            ingest_res = await ingest_url(sess, sid, url, res.content, dict(res.headers))
                            status = ingest_res.get("status")
                            if status == "ingested":
                                stat["successful"] += 1
                                stat["ingested"] += 1
                                total_new_docs += 1
                                total_signals += ingest_res.get("signals",0)
                                print(f"    [{idx+1}/{len(urls_limited)}] INGESTED {url} -> {ingest_res.get('signals')} signals (doc {ingest_res.get('doc_id')})")
                            elif status in ("duplicate_url","duplicate_hash"):
                                stat["duplicates"] += 1
                                total_duplicates += 1
                                print(f"    [{idx+1}/{len(urls_limited)}] DUPLICATE {status}: {url}")
                            elif status == "no_fashion_signal":
                                stat["successful"] += 1
                                print(f"    [{idx+1}/{len(urls_limited)}] NO_FASHION {url} (doc {ingest_res.get('doc_id')})")
                            elif status == "too_short":
                                stat["failed"] += 1
                                print(f"    [{idx+1}/{len(urls_limited)}] TOO_SHORT {url}")
                            else:
                                stat["successful"] += 1
                                print(f"    [{idx+1}/{len(urls_limited)}] {status} {url}")
                    except Exception as e:
                        import traceback
                        print(f"    [{idx+1}/{len(urls_limited)}] DB/INGEST ERROR {url}: {e}")
                        stat["failed"] += 1
                        stat["errors"].append(f"ingest {url}: {e} {traceback.format_exc()[:500]}")
                    await asyncio.sleep(RATE_LIMIT_DELAY)

                # Decide health: only mark healthy if at least one doc ingested OR no errors and sitemap reachable.
                # If ingested==0 and errors present, this is a degraded source — increment failure.
                is_failed = False
                if stat["ingested"] == 0 and stat["errors"]:
                    is_failed = True
                elif stat["ingested"] == 0 and stat["failed"] > 0 and stat["checked"] > 0 and not stat["duplicates"]:
                    # all fetches failed
                    if stat["failed"] == stat["checked"]:
                        is_failed = True

                if is_failed:
                    print(f"  Summary {sid}: discovered {stat['discovered']}, checked {stat['checked']}, ingested {stat['ingested']}, duplicates {stat['duplicates']}, failed {stat['failed']} → MARKED FAILED")
                    failed_sources.append(sid)
                    async with get_async_sessionmaker()() as s2:
                        health = await s2.get(SourceHealth, sid)
                        if not health:
                            health = SourceHealth(source_id=sid, consecutive_failures=1, last_error="; ".join(stat["errors"])[:500], is_healthy=False)
                            s2.add(health)
                        else:
                            health.consecutive_failures = (health.consecutive_failures or 0) + 1
                            health.last_error = "; ".join(stat["errors"])[:500]
                            health.is_healthy = False
                        src_row = await s2.get(Source, sid)
                        if src_row:
                            src_row.failure_count = (src_row.failure_count or 0) + 1
                            src_row.last_failed_fetch = datetime.now(timezone.utc)
                        await s2.commit()
                else:
                    async with get_async_sessionmaker()() as s2:
                        health = await s2.get(SourceHealth, sid)
                        if not health:
                            health = SourceHealth(source_id=sid, consecutive_failures=0, last_success=datetime.now(timezone.utc), is_healthy=True)
                            s2.add(health)
                        else:
                            health.consecutive_failures = 0
                            health.last_success = datetime.now(timezone.utc)
                            health.last_error = None
                            health.is_healthy = True
                            health.circuit_open_until = None
                        src_row = await s2.get(Source, sid)
                        if src_row:
                            src_row.last_successful_fetch = datetime.now(timezone.utc)
                            src_row.failure_count = 0
                        await s2.commit()
                    print(f"  Summary {sid}: discovered {stat['discovered']}, checked {stat['checked']}, ingested {stat['ingested']}, duplicates {stat['duplicates']}, failed {stat['failed']} → healthy")

                if sid not in failed_sources:
                    successful_sources.append(sid)
                per_source_stats.append(stat)

            except Exception as e:
                import traceback
                print(f"  [FATAL] source {sid} loop error: {e} {traceback.format_exc()}")
                stat["errors"].append(f"fatal: {e}")
                if sid not in failed_sources:
                    failed_sources.append(sid)
                if sid in successful_sources:
                    successful_sources.remove(sid)
                # avoid duplicate append if already appended in inner except
                if stat not in per_source_stats:
                    per_source_stats.append(stat)
                try:
                    async with get_async_sessionmaker()() as s2:
                        health = await s2.get(SourceHealth, sid)
                        if not health:
                            health = SourceHealth(source_id=sid, consecutive_failures=1, last_error=str(e)[:500], is_healthy=False)
                            s2.add(health)
                        else:
                            health.consecutive_failures = (health.consecutive_failures or 0)+1
                            health.last_error = str(e)[:500]
                            health.is_healthy = False
                        await s2.commit()
                except: pass

    # After ingestion, materialize snapshot (real-data-only when exclude_synthetic=True)
    print(f"\n=== Materializing snapshot (exclude_synthetic={exclude_synthetic}) ===")
    async with get_async_sessionmaker()() as session:
        snap = await materialize_snapshot(session, datetime.now(timezone.utc), exclude_synthetic=exclude_synthetic)
        print(f"Snapshot materialized: {len(snap)} trends (real-data-only={exclude_synthetic})")
        # Also report synthetic vs real split for verification item 8
        from sqlalchemy import func, text
        from trend_system.database.models import RawDocument as RD, FashionObservation as FO, TrendSignal as TS, TrendEvidence as TE
        real_docs = (await session.execute(select(func.count()).select_from(RD).where(RD.is_synthetic == False))).scalar()
        syn_docs = (await session.execute(select(func.count()).select_from(RD).where(RD.is_synthetic == True))).scalar()
        # real observations/signals: join raw_documents is_synthetic
        real_obs = (await session.execute(text("SELECT COUNT(*) FROM fashion_observations fo JOIN raw_documents rd ON fo.raw_document_id=rd.id WHERE rd.is_synthetic=0"))).scalar()
        syn_obs = (await session.execute(text("SELECT COUNT(*) FROM fashion_observations fo JOIN raw_documents rd ON fo.raw_document_id=rd.id WHERE rd.is_synthetic=1"))).scalar()
        real_sigs = (await session.execute(text("SELECT COUNT(*) FROM trend_signals ts JOIN raw_documents rd ON ts.raw_document_id=rd.id WHERE rd.is_synthetic=0"))).scalar()
        syn_sigs = (await session.execute(text("SELECT COUNT(*) FROM trend_signals ts JOIN raw_documents rd ON ts.raw_document_id=rd.id WHERE rd.is_synthetic=1"))).scalar()
        # evidence chain: count evidence where linked raw is real vs syn
        # need to handle sqlite bool
        try:
            real_ev = (await session.execute(text("SELECT COUNT(*) FROM trend_evidence te JOIN raw_documents rd ON te.raw_document_id=rd.id WHERE rd.is_synthetic=0"))).scalar()
            syn_ev = (await session.execute(text("SELECT COUNT(*) FROM trend_evidence te JOIN raw_documents rd ON te.raw_document_id=rd.id WHERE rd.is_synthetic=1"))).scalar()
        except:
            real_ev = syn_ev = 0
        print(f"  Real docs: {real_docs}, synthetic docs: {syn_docs}")
        print(f"  Real observations: {real_obs}, synthetic: {syn_obs}")
        print(f"  Real signals: {real_sigs}, synthetic: {syn_sigs}")
        print(f"  Real trend_evidence: {real_ev}, synthetic: {syn_ev}")
        # Cross-source support (real-only)
        if snap:
            for t in snap[:5]:
                print(f"    - {t['trend']}: score {t['trend_score']} sources {t['supporting_sources']} ev {t['evidence_count']} actionable {t['is_actionable']}")

    end_time = datetime.now(timezone.utc)
    async with get_async_sessionmaker()() as session:
        cr = await session.get(CollectionRun, run_id)
        cr.finished_at = end_time
        cr.sources_successful = len(successful_sources)
        cr.sources_failed = len(failed_sources)
        cr.new_documents = total_new_docs
        cr.duplicates = total_duplicates
        cr.fashion_signals = total_signals
        cr.status = "partial" if failed_sources else "success"
        cr.error_log = {"per_source": per_source_stats, "successful": successful_sources, "failed": failed_sources, "exclude_synthetic": exclude_synthetic}
        await session.commit()
        print(f"\n=== CollectionRun {run_id} finished ===")
        print(f"  Sources checked: {cr.sources_checked}, successful: {cr.sources_successful}, failed: {cr.sources_failed} ({failed_sources})")
        print(f"  New documents: {cr.new_documents}, duplicates: {cr.duplicates}, signals: {cr.fashion_signals}")
        print(f"  Status: {cr.status}")

    return {
        "run_id": run_id,
        "per_source": per_source_stats,
        "total_new_docs": total_new_docs,
        "total_signals": total_signals,
        "snapshot_count": len(snap) if 'snap' in locals() else 0,
        "successful_sources": successful_sources,
        "failed_sources": failed_sources,
        "exclude_synthetic": exclude_synthetic,
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=MAX_URLS_PER_SOURCE, help="max URLs per source")
    parser.add_argument("--include-synthetic", action="store_true", help="include synthetic seed in snapshot (testing only)")
    args = parser.parse_args()
    res = asyncio.run(live_run(limit_per_source=args.limit, exclude_synthetic=not args.include_synthetic))
    print("\n=== FINAL RESULT ===")
    print(res)
