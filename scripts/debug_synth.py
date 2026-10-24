import asyncio, uuid, hashlib
from datetime import datetime, timezone, timedelta
from trend_system.database.session import get_async_sessionmaker, init_db
from trend_system.database.models import FashionEntity, RawDocument, FashionObservation, TrendSignal
from trend_system.utils.calendar import to_jalali_dict
from trend_system.scheduler.snapshot import materialize_snapshot

async def main():
    await init_db()
    concept = f"__synth_iso_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    pub_real = now - timedelta(days=1)
    pub_synth = now - timedelta(days=2)
    async with get_async_sessionmaker()() as session:
        ent = FashionEntity(canonical_name=concept, category="garment", aliases=[], iran_compatibility=0.7)
        session.add(ent)
        await session.flush()
        async def make_doc(is_synth, ts):
            title = f"synth iso {'synthetic' if is_synth else 'real'} {concept}"
            content = f"{title} content {uuid.uuid4().hex[:4]}"
            h = hashlib.sha256((content+str(is_synth)).encode()).hexdigest()
            url = f"https://example.com/test/synth_iso/{concept}/{'s' if is_synth else 'r'}/{uuid.uuid4().hex[:6]}"
            jalali = to_jalali_dict(ts)
            doc = RawDocument(source_id="vogue", source_url=url, title=title, content_html=f"<html><body>{content}</body></html>", content_text=content, publication_date_utc=ts, publication_date_jalali=jalali["jalali_date"], publication_season=jalali["season"], publication_jalali_month=jalali["jalali_month"], publication_gregorian_month=ts.month, collection_date_utc=now, language="en", is_synthetic=is_synth, content_hash=h)
            session.add(doc)
            await session.flush()
            obs = FashionObservation(raw_document_id=doc.id, source_id="vogue", entity_id=concept, raw_term=concept, canonical_name=concept, category="garment", confidence=0.9, extractor_type="rule", span_text=content[:80], observed_at=ts, region="global")
            session.add(obs)
            await session.flush()
            sig = TrendSignal(concept=concept, source_id="vogue", observation_id=obs.id, raw_document_id=doc.id, timestamp_utc=ts, timestamp_jalali=jalali["jalali_date"], jalali_month=jalali["jalali_month"], season=jalali["season"], evidence_type="article", confidence=0.9, region="global")
            session.add(sig)
            await session.flush()
            return doc, obs, sig
        real_doc, real_obs, real_sig = await make_doc(False, pub_real)
        synth_doc, synth_obs, synth_sig = await make_doc(True, pub_synth)
        await session.commit()
        # verify signals exist
        from sqlalchemy import select as sel, text as txt
        res = await session.execute(sel(TrendSignal).where(TrendSignal.concept == concept))
        sigs = res.scalars().all()
        print(f"signals for {concept}: {len(sigs)}", [(s.concept, s.timestamp_utc, s.region) for s in sigs])
        rd_res = await session.execute(txt("SELECT source_url, is_synthetic FROM raw_documents WHERE source_url LIKE :p"), {"p": f"%{concept}%"})
        print("raw docs for concept:", rd_res.fetchall())
        # Replicate snapshot query
        from datetime import timedelta as td
        window_start = now - td(days=30)
        q = txt("""
        SELECT ts.concept, ts.source_id, ts.timestamp_utc, rd.is_synthetic
        FROM trend_signals ts
        LEFT JOIN raw_documents rd ON ts.raw_document_id = rd.id
        WHERE ts.timestamp_utc <= :snap AND ts.timestamp_utc >= :window_start AND (rd.is_synthetic IS NULL OR rd.is_synthetic = 0 OR rd.is_synthetic = '0' OR rd.is_synthetic = 'false')
        """)
        rows = await session.execute(q, {"snap": now, "window_start": window_start})
        found_concepts = [r[0] for r in rows.fetchall()]
        print("snapshot query concepts (exclude synth):", set(found_concepts))
        print("new concept in query?", concept in found_concepts)
        t_real = now
        payload = await materialize_snapshot(session, snapshot_time=t_real, exclude_synthetic=True)
        print("concept repr:", repr(concept))
        print("payload keys repr:", [repr(p["canonical_name"]) for p in payload[:15]])
        our = next((t for t in payload if t["canonical_name"]==concept), None)
        print("found:", our)
        print("total trends:", len(payload))
        # also check if concept in payload keys via set
        print("concept in keys:", concept in [p["canonical_name"] for p in payload])
        print("exact match loop:")
        for p in payload:
            if p["canonical_name"] == concept:
                print("  MATCH FOUND", p)
                break
        else:
            print("  NO MATCH")
        # also check with include synthetic
        t2 = t_real + timedelta(seconds=1)
        payload2 = await materialize_snapshot(session, snapshot_time=t2, exclude_synthetic=False)
        our2 = next((t for t in payload2 if t["canonical_name"]==concept), None)
        print("with synthetic found:", our2)
        print("evidence counts:", our["evidence_count"] if our else None, our2["evidence_count"] if our2 else None)
        # cleanup
        from sqlalchemy import text, select
        from trend_system.database.models import TrendSnapshot
        for snap_time in [t_real, t2]:
            srow = await session.execute(select(TrendSnapshot).where(TrendSnapshot.snapshot_time_utc == snap_time))
            s = srow.scalars().first()
            if s:
                await session.delete(s)
        await session.execute(text("DELETE FROM trend_history WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_evidence WHERE trend_id = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trends WHERE canonical_name = :c"), {"c": concept})
        await session.execute(text("DELETE FROM trend_signals WHERE concept = :c"), {"c": concept})
        await session.execute(text("DELETE FROM fashion_observations WHERE raw_document_id IN (:r1, :r2)"), {"r1": real_doc.id, "r2": synth_doc.id})
        await session.execute(text("DELETE FROM raw_documents WHERE id IN (:r1, :r2)"), {"r1": real_doc.id, "r2": synth_doc.id})
        await session.execute(text("DELETE FROM fashion_entities WHERE canonical_name = :c"), {"c": concept})
        await session.commit()

asyncio.run(main())
