"""Raw document ingestion → observations → trend signals.

The pipeline keeps the full provenance chain:

    RawDocument → FashionObservation → TrendSignal → (TrendEvidence)

Deduplication is exact (canonical URL then content hash).  Short documents and
documents without any fashion entity are stored for audit purposes but produce
no trend signal.  Region is always ``global`` in the active pipeline; the
Iranian region is only retained for historical rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from trend_system.config import get_llm_config, get_settings, get_taxonomy_config
from trend_system.database.models import (
    FashionEntity,
    FashionObservation,
    LLMCache,
    RawDocument,
    Source,
    TrendSignal,
)
from trend_system.extraction.fashion_extractor import (
    extract_fashion_attributes,
    extraction_confidence,
)
from trend_system.extraction.llm_provider import get_llm_provider, llm_cache_key
from trend_system.extraction.season_extractor import normalize_season_tag
from trend_system.extraction.text_extractor import extract_clean_text
from trend_system.normalization.taxonomy import get_category, lookup_canonical
from trend_system.utils.calendar import to_jalali_dict

logger = logging.getLogger(__name__)

MIN_CONTENT_CHARS = 100
_PROMPT_VERSION = "fashion_extract_v1"
_TAXONOMY_VERSION = "global_v1"

_CATEGORY_TO_FIELD = {
    "garment": "garments",
    "outerwear": "garments",
    "footwear": "garments",
    "accessory": "garments",
    "color": "colors",
    "pattern": "patterns",
    "material": "materials",
    "silhouette": "silhouettes",
    "style": "styles",
    "styling": "styles",
    "aesthetic": "styles",
    "occasion": "styles",
    "macro_trend": "styles",
    "micro_trend": "styles",
    "designer": "styles",
    "outfit_combination": "outfit_combinations",
}


async def _ensure_source(session, source_id: str) -> Source:
    source = await session.get(Source, source_id)
    if source is not None:
        return source
    logger.warning("Source %s missing from database; creating a minimal record", source_id)
    source = Source(
        source_id=source_id,
        name=source_id,
        source_type="editorial",
        region="global",
        language="en",
        authority_weight=0.5,
        freshness_weight=0.5,
        enabled=True,
        scope="global",
        source_region="global",
    )
    session.add(source)
    await session.flush()
    return source


async def _ensure_entity(session, canonical: str, category: str) -> FashionEntity:
    entity = await session.get(FashionEntity, canonical)
    if entity is not None:
        return entity
    entity = FashionEntity(
        canonical_name=canonical,
        category=category,
        aliases=[],
        scope="global",
        source_region="global",
    )
    session.add(entity)
    await session.flush()
    return entity


async def _llm_candidates(session, text: str, title: str | None, language: str, content_hash: str) -> list[str]:
    """Optional LLM extraction, cached in ``llm_cache``. Disabled by default."""
    settings = get_settings()
    llm_cfg = get_llm_config() or {}
    enabled = llm_cfg.get("enabled", False)
    if settings.LLM_ENABLED is not None:
        enabled = settings.LLM_ENABLED
    if not enabled:
        return []

    provider = get_llm_provider()
    provider_model = settings.LLM_MODEL or llm_cfg.get("model", "dummy")
    cache_key = llm_cache_key(content_hash, _PROMPT_VERSION, _TAXONOMY_VERSION, str(provider_model))
    cached = await session.get(LLMCache, cache_key)
    if cached is not None:
        cached.hit_count = (cached.hit_count or 0) + 1
        return list((cached.output_json or {}).get("trend_candidates", []))

    taxonomy_hint = [
        ent.get("canonical")
        for ent in (get_taxonomy_config() or {}).get("entities", [])
        if ent.get("canonical")
    ][:80]
    try:
        result = await provider.extract(text[:4000], title, taxonomy_hint, language)
    except Exception as exc:
        logger.info("LLM extraction skipped: %s", exc)
        return []

    session.add(
        LLMCache(
            cache_key=cache_key,
            prompt_version=_PROMPT_VERSION,
            provider_model=str(provider_model),
            input_hash=content_hash,
            output_json=result,
        )
    )
    return list(result.get("trend_candidates", []))


def _context_snippet(text: str, term: str, fallback: str) -> str:
    lowered = text.lower()
    idx = lowered.find(term.lower())
    if idx < 0:
        return (fallback or text[:200]).strip()
    start = max(0, idx - 60)
    end = min(len(text), idx + len(term) + 60)
    return text[start:end].strip()


async def ingest_url(
    session,
    source_id: str,
    url: str,
    html: str,
    headers: dict | None = None,
    published_hint: datetime | None = None,
) -> dict:
    """Ingest one fetched article. Returns a status dict (never raises for data issues)."""
    now = datetime.now(timezone.utc)
    source = await _ensure_source(session, source_id)

    existing_by_url = (
        await session.execute(select(RawDocument).where(RawDocument.source_url == url))
    ).scalars().first()
    if existing_by_url is not None:
        return {
            "status": "duplicate_url",
            "doc_id": existing_by_url.id,
            "signals": 0,
        }

    extracted = extract_clean_text(html, url)
    content_text = (extracted.get("content_text") or "").strip()
    if len(content_text) < MIN_CONTENT_CHARS:
        return {"status": "too_short", "doc_id": None, "signals": 0}

    content_hash = extracted.get("content_hash")
    existing_by_hash = (
        await session.execute(select(RawDocument).where(RawDocument.content_hash == content_hash))
    ).scalars().first()
    if existing_by_hash is not None:
        return {
            "status": "duplicate_hash",
            "doc_id": existing_by_hash.id,
            "signals": 0,
        }

    title = extracted.get("title") or ""
    language = extracted.get("language") or "en"
    publication_dt = extracted.get("parsed_pub") or published_hint or now
    if publication_dt.tzinfo is None:
        publication_dt = publication_dt.replace(tzinfo=timezone.utc)
    if publication_dt > now:
        # Do not create future-dated evidence (point-in-time correctness).
        publication_dt = now
    jalali = to_jalali_dict(publication_dt)

    found = extract_fashion_attributes(content_text, title=title, language=language)

    llm_terms = await _llm_candidates(session, content_text, title, language, content_hash)
    for term in llm_terms:
        canonical, _category = lookup_canonical(str(term))
        canonical = canonical or str(term).strip().lower().replace(" ", "_")
        if canonical and canonical not in found["trend_candidates"]:
            found["trend_candidates"].append(canonical)

    confidence = extraction_confidence(found)

    document = RawDocument(
        source_id=source_id,
        source_url=url,
        canonical_url=url.split("?")[0],
        title=title or None,
        content_html=html,
        content_text=content_text,
        publication_date_utc=publication_dt,
        publication_date_jalali=jalali["jalali_date"],
        publication_season=normalize_season_tag(title, default=jalali["season"]) if title else jalali["season"],
        publication_jalali_month=jalali["jalali_month"],
        publication_gregorian_month=publication_dt.month,
        collection_date_utc=now,
        language=language,
        author=extracted.get("author"),
        image_urls=extracted.get("image_urls") or [],
        meta={"extractor": "rule+gazetteer", "headers": headers or {}},
        content_hash=content_hash,
        extraction_timestamp=now,
        is_synthetic=False,
    )
    session.add(document)
    await session.flush()

    if not found["trend_candidates"]:
        source.last_successful_fetch = now
        await session.commit()
        return {"status": "no_fashion_signal", "doc_id": document.id, "signals": 0}

    concept_categories: dict[str, str] = {}
    for canonical in found["trend_candidates"]:
        category = get_category(canonical) or "unknown"
        concept_categories.setdefault(canonical, category)

    signals = 0
    for canonical, category in concept_categories.items():
        await _ensure_entity(session, canonical, category)

        attributes = {
            key: found.get(field, [])
            for key, field in _CATEGORY_TO_FIELD.items()
            if found.get(field)
        }
        observation = FashionObservation(
            raw_document_id=document.id,
            source_id=source_id,
            entity_id=canonical,
            raw_term=canonical,
            canonical_name=canonical,
            category=category,
            confidence=confidence,
            extractor_type="rule",
            span_text=_context_snippet(content_text, canonical.replace("_", " "), title)[:1000],
            attributes=attributes or None,
            observed_at=publication_dt,
            region="global",
        )
        session.add(observation)
        await session.flush()

        session.add(
            TrendSignal(
                concept=canonical,
                source_id=source_id,
                observation_id=observation.id,
                raw_document_id=document.id,
                timestamp_utc=publication_dt,
                timestamp_jalali=jalali["jalali_date"],
                jalali_month=jalali["jalali_month"],
                season=normalize_season_tag(title, default=jalali["season"]) if title else jalali["season"],
                evidence_type="article",
                confidence=confidence,
                region="global",
                extracted_attributes=attributes or None,
            )
        )
        signals += 1

    source.last_successful_fetch = now
    source.failure_count = 0
    await session.commit()

    return {
        "status": "ingested",
        "doc_id": document.id,
        "signals": signals,
        "concepts": sorted(concept_categories),
        "language": language,
        "publication_date_utc": publication_dt.isoformat(),
    }
