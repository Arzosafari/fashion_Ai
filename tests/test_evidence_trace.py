"""Full provenance chain: Trend → TrendEvidence → TrendSignal → FashionObservation → RawDocument"""
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
async def test_evidence_trace_chain():
    """Create a fresh concept with full chain, materialize snapshot, then reconstruct.

    Verifies:
      - TrendEvidence exists for each signal
      - TrendEvidence links to correct TrendSignal, FashionObservation, RawDocument
      - All provenance fields are meaningful (non-empty, correct types)
      - Chain is reconstructable via FKs
    """
    await init_db()
    concept = f"__evidence_test_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    pub = now - timedelta(hours=2)
    jalali = to_jalali_dict(pub)
    title = f"Evidence trace article for {concept}"
    content = f"{title} Wide leg tailoring and manteau styling — evidence trace {uuid.uuid4().hex[:4]}"

    async with get_async_sessionmaker()() as session:
        # Ensure source and entity
        src = await session.get(Source, "vogue")
        assert src is not None
        ent = await session.get(FashionEntity, concept)
        if not ent:
            ent = FashionEntity(canonical_name=concept, category="garment", aliases=[], iran_compatibility=0.6)
            session.add(ent)
            await session.flush()

        import hashlib
        h = hashlib.sha256(content.encode()).hexdigest()
        url = f"https://example.com/test/evidence/{concept}/{uuid.uuid4().hex[:6]}"
        doc = RawDocument(
            source_id="vogue",
            source_url=url,
            title=title,
            content_html=f"<html><body>{content}</body></html>",
            content_text=content,
            publication_date_utc=pub,
            publication_date_jalali=jalali["jalali_date"],
            publication_season=jalali["season"],
            publication_jalali_month=jalali["jalali_month"],
            publication_gregorian_month=pub.month,
            collection_date_utc=now,
            language="en",
            is_synthetic=False,
            content_hash=h,
        )
        session.add(doc)
        await session.flush()
        assert doc.id is not None
        assert doc.content_hash == h
        assert doc.title == title
        assert doc.source_url == url
        assert doc.language in ("en", "fa")

        obs = FashionObservation(
            raw_document_id=doc.id,
            source_id="vogue",
            entity_id=concept,
            raw_term=concept,
            canonical_name=concept,
            category="garment",
            confidence=0.88,
            extractor_type="rule",
            span_text=content[:100],
            observed_at=pub,
            region="global",
        )
        session.add(obs)
        await session.flush()
        assert obs.id is not None
        assert obs.canonical_name == concept
        assert obs.confidence == 0.88
        assert obs.extractor_type in ("rule","llm","hybrid")

        sig = TrendSignal(
            concept=concept,
            source_id="vogue",
            observation_id=obs.id,
            raw_document_id=doc.id,
            timestamp_utc=pub,
            timestamp_jalali=jalali["jalali_date"],
            jalali_month=jalali["jalali_month"],
            season=jalali["season"],
            evidence_type="article",
            confidence=0.88,
            region="global",
        )
        session.add(sig)
        await session.flush()
        assert sig.id is not None
        assert sig.concept == concept
        assert sig.timestamp_utc == pub

        await session.commit()

        # Materialize snapshot including this signal (use recent snapshot_time = now)
        snapshot_time = now
        payload = await materialize_snapshot(session, snapshot_time=snapshot_time, exclude_synthetic=False)
        our = next((t for t in payload if t["canonical_name"] == concept), None)
        assert our is not None, f"trend {concept} must appear in snapshot"
        assert our["evidence_count"] >= 1
        assert our["supporting_sources"] == 1
        assert "explanation" in our and len(our["explanation"]) > 10, "explanation must be meaningful"
        assert "components" in our

        # Fetch Trend row
        tr = await session.get(Trend, concept)
        assert tr is not None
        assert tr.explanation and len(tr.explanation) > 5
        assert tr.current_score is not None and 0 < tr.current_score <= 1

        # Fetch TrendEvidence and walk the chain
        ev_res = await session.execute(select(TrendEvidence).where(TrendEvidence.trend_id == concept))
        evs = ev_res.scalars().all()
        assert len(evs) >= 1, "at least one TrendEvidence required"
        ev = evs[0]
        # Provenance fields must be meaningful
        assert ev.source_id == "vogue"
        assert ev.signal_id == sig.id
        assert ev.observation_id == obs.id
        assert ev.raw_document_id == doc.id
        assert ev.evidence_type in ("article","social","search","product")
        assert ev.confidence is not None and 0 < ev.confidence <= 1
        assert ev.timestamp_utc is not None
        # snippet meaningful
        assert ev.snippet is not None and len(ev.snippet.strip()) >= 5
        assert ev.timestamp_jalali is not None

        # Hop: TrendEvidence -> TrendSignal
        sig2 = await session.get(TrendSignal, ev.signal_id)
        assert sig2 is not None
        assert sig2.concept == concept
        assert sig2.raw_document_id == doc.id
        assert sig2.observation_id == obs.id
        assert sig2.timestamp_utc is not None
        assert sig2.evidence_type is not None

        # Hop: TrendSignal -> FashionObservation
        obs2 = await session.get(FashionObservation, sig2.observation_id)
        assert obs2 is not None
        assert obs2.raw_document_id == doc.id
        assert obs2.canonical_name == concept
        assert obs2.confidence is not None

        # Hop: FashionObservation / TrendSignal -> RawDocument
        doc2 = await session.get(RawDocument, ev.raw_document_id)
        assert doc2 is not None
        assert doc2.source_url.startswith("https://example.com/test/evidence/")
        assert doc2.title == title
        assert doc2.content_hash == h
        assert doc2.content_text and len(doc2.content_text) > 20
        assert doc2.language is not None

        # Full reconstructability proof: trend_id -> evidence -> signal -> observation -> raw
        # Already proved above via equality of IDs.

        # Cleanup — delete in FK-safe order
        # snapshot that we just created (unique time = now) — delete it to keep DB clean
        snap_row = await session.execute(select(TrendSnapshot).where(TrendSnapshot.snapshot_time_utc == snapshot_time))
        snap = snap_row.scalars().first()
        if snap:
            # Check if this snapshot is the one we created (contains our concept)
            if any(t.get("canonical_name")==concept for t in (snap.trends or [])):
                await session.delete(snap)
                await session.flush()
        await session.execute(text("DELETE FROM trend_history WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_evidence WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trends WHERE canonical_name = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_signals WHERE concept = :c"), {"c": concept})
        await session.execute(text("DELETE FROM fashion_observations WHERE raw_document_id = :did"), {"did": doc.id})
        await session.execute(text("DELETE FROM raw_documents WHERE id = :did"), {"did": doc.id})
        await session.execute(text("DELETE FROM fashion_entities WHERE canonical_name = :c"), {"c": concept})
        await session.commit()

@pytest.mark.asyncio
async def test_evidence_synthetic_isolation():
    """Synthetic signals must not contaminate production scoring when exclude_synthetic=True.

    Create two signals for same concept: one synthetic (is_synthetic=True) and one real.
    Snapshot with exclude_synthetic=True must count only the real one.
    """
    await init_db()
    concept = f"__synth_iso_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    pub_real = now - timedelta(days=1)
    pub_synth = now - timedelta(days=2)
    import hashlib

    async with get_async_sessionmaker()() as session:
        # Ensure entity
        ent = await session.get(FashionEntity, concept)
        if not ent:
            ent = FashionEntity(canonical_name=concept, category="garment", aliases=[], iran_compatibility=0.7)
            session.add(ent)
            await session.flush()

        async def make_doc(is_synth: bool, ts: datetime):
            title = f"synth iso {'synthetic' if is_synth else 'real'} {concept}"
            content = f"{title} content {uuid.uuid4().hex[:4]}"
            h = hashlib.sha256((content+str(is_synth)).encode()).hexdigest()
            url = f"https://example.com/test/synth_iso/{concept}/{'s' if is_synth else 'r'}/{uuid.uuid4().hex[:6]}"
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
                collection_date_utc=now,
                language="en",
                is_synthetic=is_synth,
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
                span_text=content[:80],
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

        real_doc, real_obs, real_sig = await make_doc(False, pub_real)
        synth_doc, synth_obs, synth_sig = await make_doc(True, pub_synth)
        await session.commit()

        # Snapshot excluding synthetic — must see only real
        t_real = now
        payload_real_only = await materialize_snapshot(session, snapshot_time=t_real, exclude_synthetic=True)
        our_real = next((t for t in payload_real_only if t["canonical_name"]==concept), None)
        assert our_real is not None, "real-only snapshot should contain concept (real signal exists)"
        assert our_real["evidence_count"] == 1, f"real-only evidence_count should be 1, got {our_real['evidence_count']}"

        # Snapshot including synthetic — must see both
        t2 = t_real + timedelta(seconds=1)  # distinct snapshot time
        payload_all = await materialize_snapshot(session, snapshot_time=t2, exclude_synthetic=False)
        our_all = next((t for t in payload_all if t["canonical_name"]==concept), None)
        assert our_all is not None
        # May be 2 now (both signals), but at least evidence_count > real-only
        assert our_all["evidence_count"] == 2, f"inclusive evidence_count should be 2, got {our_all['evidence_count']}"
        assert our_all["evidence_count"] > our_real["evidence_count"]

        # Ensure TrendEvidence respects mode: real-only snapshot created only 1 evidence row before second snapshot
        # After both snapshots, total evidence rows should be 2 (one per signal, dedup per signal+trend)
        # But the key is that first snapshot's payload evidence_count was 1.
        # Clean up
        for snap_time in [t_real, t2]:
            srow = await session.execute(select(TrendSnapshot).where(TrendSnapshot.snapshot_time_utc == snap_time))
            s = srow.scalars().first()
            if s and any(t.get("canonical_name")==concept for t in (s.trends or [])):
                await session.delete(s)
                await session.flush()
        await session.execute(text("DELETE FROM trend_history WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_evidence WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trends WHERE canonical_name = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_signals WHERE concept = :c"), {"c": concept})
        await session.execute(text("DELETE FROM fashion_observations WHERE raw_document_id IN (:r1, :r2)"), {"r1": real_doc.id, "r2": synth_doc.id})
        await session.execute(text("DELETE FROM raw_documents WHERE id IN (:r1, :r2)"), {"r1": real_doc.id, "r2": synth_doc.id})
        await session.execute(text("DELETE FROM fashion_entities WHERE canonical_name = :c"), {"c": concept})
        await session.commit()
