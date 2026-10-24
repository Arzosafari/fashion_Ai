"""Point-in-time snapshot isolation — future data must not leak."""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, text, func
from trend_system.database.session import get_async_sessionmaker, init_db
from trend_system.database.models import (
    RawDocument, FashionObservation, TrendSignal, FashionEntity, Source, Trend, TrendHistory, TrendSnapshot, TrendEvidence
)
from trend_system.scheduler.snapshot import materialize_snapshot
from trend_system.utils.calendar import to_jalali_dict

@pytest.mark.asyncio
async def test_snapshot_point_in_time():
    """Prove future TrendSignals cannot enter a snapshot anchored at an earlier time.

    Creates a dedicated concept with two signals — one in the past and one 7 days
    in the future relative to an explicit snapshot_time. Snapshot must contain
    only the past signal (evidence_count == 1).
    """
    await init_db()
    concept = f"__temporal_pt_{uuid.uuid4().hex[:6]}"
    snapshot_time = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    past_time = snapshot_time - timedelta(days=1)
    future_time = snapshot_time + timedelta(days=7)

    async with get_async_sessionmaker()() as session:
        # Ensure source exists (vogue)
        src = await session.get(Source, "vogue")
        assert src is not None, "source vogue must be seeded"

        # Ensure entity exists
        ent = await session.get(FashionEntity, concept)
        if not ent:
            ent = FashionEntity(canonical_name=concept, category="garment", aliases=[], iran_compatibility=0.7)
            session.add(ent)
            await session.flush()

        # Helper to create raw doc + observation + signal at given time
        async def make_chain(ts: datetime, suffix: str):
            title = f"temporal test article {suffix}"
            content = f"{title} content for {concept} at {ts.isoformat()}"
            import hashlib
            h = hashlib.sha256(content.encode()).hexdigest()
            url = f"https://example.com/test/temporal/{concept}/{suffix}/{uuid.uuid4().hex[:4]}"
            jalali = to_jalali_dict(ts)
            doc = RawDocument(
                source_id="vogue",
                source_url=url,
                title=title,
                content_html=f"<html><body>{content}</body></html>",
                content_text=content,
                publication_date_utc=ts,
                publication_date_jalali=jalali["jalali_date"],
                publication_season=jalali["season"],
                publication_jalali_month=jalali["jalali_month"],
                publication_gregorian_month=ts.month,
                collection_date_utc=datetime.now(timezone.utc),
                language="en",
                is_synthetic=False,
                content_hash=h,
            )
            session.add(doc)
            await session.flush()
            obs = FashionObservation(
                raw_document_id=doc.id,
                source_id="vogue",
                entity_id=concept,
                raw_term=concept,
                canonical_name=concept,
                category="garment",
                confidence=0.9,
                extractor_type="rule",
                span_text=content[:100],
                observed_at=ts,
                region="global",
            )
            session.add(obs)
            await session.flush()
            sig = TrendSignal(
                concept=concept,
                source_id="vogue",
                observation_id=obs.id,
                raw_document_id=doc.id,
                timestamp_utc=ts,
                timestamp_jalali=jalali["jalali_date"],
                jalali_month=jalali["jalali_month"],
                season=jalali["season"],
                evidence_type="article",
                confidence=0.9,
                region="global",
            )
            session.add(sig)
            await session.flush()
            return doc, obs, sig

        # Cleanup any stale test data for this concept (if previous run leaked)
        # (no-op for unique uuid, but keep for safety if re-used)
        # Create past and future chains
        past_doc, past_obs, past_sig = await make_chain(past_time, "past")
        future_doc, future_obs, future_sig = await make_chain(future_time, "future")
        await session.commit()

        # Record counts before snapshot to detect leakage
        # Ensure both signals exist
        res = await session.execute(select(func.count()).select_from(TrendSignal).where(TrendSignal.concept == concept))
        assert res.scalar() == 2

        # Materialize snapshot anchored at snapshot_time — must NOT include future
        # Use exclude_synthetic=False (real data test) but our docs are real (is_synthetic=False)
        payload = await materialize_snapshot(session, snapshot_time=snapshot_time, exclude_synthetic=False)

        # Find our concept in payload
        our_trend = next((t for t in payload if t["canonical_name"] == concept), None)
        assert our_trend is not None, f"trend {concept} should appear (past signal within window)"
        # Critical: future signal must not have been counted
        assert our_trend["evidence_count"] == 1, f"evidence_count {our_trend['evidence_count']} should be 1 (future excluded), got {our_trend}"
        assert our_trend["supporting_sources"] == 1
        # last_updated must be past_time, not future_time, and <= snapshot_time
        from dateutil import parser as dp
        last = dp.parse(our_trend["last_updated"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        assert last == past_time or abs((last - past_time).total_seconds()) < 2, f"last_updated {last} should equal past_time {past_time}"
        assert last <= snapshot_time
        # Ensure payload does not contain future timestamp anywhere for this concept
        # Query TrendEvidence for this concept — should have only 1 row (past)
        ev_res = await session.execute(select(TrendEvidence).where(TrendEvidence.trend_id == concept))
        evs = ev_res.scalars().all()
        assert len(evs) == 1, f"TrendEvidence should be 1 (future not materialized), got {len(evs)}"
        assert evs[0].signal_id == past_sig.id
        assert evs[0].timestamp_utc == past_time or str(evs[0].timestamp_utc)[:16] == str(past_time)[:16]

        # Cleanup test data after assertions — remove in reverse FK order
        # Delete history, evidence, snapshot containing our concept? Snapshot is JSON; we delete snapshot row we just created.
        snap_row = await session.execute(select(TrendSnapshot).where(TrendSnapshot.snapshot_time_utc == snapshot_time))
        snap = snap_row.scalars().first()
        if snap:
            await session.delete(snap)
            await session.flush()
        # Delete history for concept
        await session.execute(text("DELETE FROM trend_history WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_evidence WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trends WHERE canonical_name = :c"), {"c": concept})
        # Delete signals/observations/docs for concept
        await session.execute(text("DELETE FROM trend_signals WHERE concept = :c"), {"c": concept})
        # Observations via raw doc join
        # Safer: delete observations that reference our docs
        await session.execute(text("DELETE FROM fashion_observations WHERE raw_document_id IN (SELECT id FROM raw_documents WHERE source_url LIKE :u)"), {"u": f"%temporal/{concept}%"})
        await session.execute(text("DELETE FROM raw_documents WHERE source_url LIKE :u"), {"u": f"%temporal/{concept}%"})
        await session.execute(text("DELETE FROM fashion_entities WHERE canonical_name = :c"), {"c": concept})
        await session.commit()

        # Final sanity: ensure future signal was still present before cleanup? Already removed.
        # The test proves aggregation query uses timestamp_utc <= :snap.

