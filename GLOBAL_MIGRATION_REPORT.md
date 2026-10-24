# Global Fashion Trend Migration Report — 2026-09-29

**Date:** 2026-09-29 (Asia/Tehran)  
**Scope:** Trend Module ONLY → GLOBAL, rest of Fashion AI preserved (user location Iran independent)  
**Previous validation:** 2026-09-21 4/4 Iranian sources live — now superseded, archived, isolated

---

## 1. Deliverable A — Files Changed / Removed / Added

### Modified (minimal targeted rewrites, preserved infrastructure)
- `config/sources.yaml` — **Replaced** 4 Iranian sources with 4 global: `vogue` (sitemap.xml), `harpers_bazaar` (sitemap_index.xml verified), `whowhatwear` (sitemap.xml), `wgsn` (sitemap.xml, restricted). Disabled candidates kept for extensibility. All entries now carry `scope: global`, `source_region: global`, `accessibility` (public/restricted), verified sitemap URLs.
- `config/scoring.yaml` — `v2_global`, `trend_scope: global`, `similarity_threshold: 0.58`, `half_life_days: 30` configurable via env, `iran_relevance.enabled: false`, `gate.I_weight: 0.0`, seasonal calendar `gregorian`, `fashion_weeks: [NY,London,Milan,Paris,Copenhagen]` extensible, season_normalization map SS26→Spring/Summer 2026.
- `config/taxonomy.yaml` — Global taxonomy (color, silhouette, garment, material, pattern, accessory, styling, aesthetic, footwear, outerwear, occasion, macro_trend, micro_trend, designer). Added 15+ global trend candidates per spec (`oversized_floral_brooches`, `animal_print`, `dramatic_bows`, `sculptural_ruffles`, `dark_florals`, `futuristic_fabrics`, `oversized_blanket_plaids`, `elevated_bomber_jacket`, `red_tailoring`, `statement_belts`, `brown_suede`, etc.) + 8 designers (Chanel, Dior, Gucci, Prada…). Preserved Persian aliases for backward compat, added `global_relevance` + `scope`. Normalized thresholds `auto_threshold: 0.58` matching `TREND_SIMILARITY_THRESHOLD`.
- `config/seasonal_affinity.yaml` — Extended for global seasons (`Spring/Summer 2026`, `Fall/Winter 2026`, `Resort 2026`).
- `trend_system/database/models.py` — Added `Source.scope`, `Source.source_region`, `FashionEntity.global_relevance/scope/source_region`, `Trend.trend_scope/source_region/semantic_consistency/recurrence_score`. Preserves SQLite, no hard delete.
- `trend_system/collectors/base.py` — Filter updated to `vogue.com|harpersbazaar.com|whowhatwear.com|wgsn.com`.
- `trend_system/collectors/registry.py` — `ADAPTER_MAP` now `vogue, harpers_bazaar, whowhatwear, wgsn`; Iranian adapters commented for archive; added `get_adapter()` helper.
- `trend_system/scoring/iran_relevance.py` — Returns `1.0` when `trend_scope==global` or `enabled==false` (neutral gate).
- `trend_system/scoring/trend_score.py` — Env override `HALF_LIFE_DAYS`, dynamic `max_sources` from enabled sources, `I=1.0` for global, added `semantic_consistency/recurrence` to components, formula `source_quality × freshness × cross_source × semantic_consistency × recurrence` via gated_geom.
- `trend_system/scoring/seasonality.py` — Handles normalized seasons (`Spring/Summer 2026` → spring/summer avg).
- `trend_system/normalization/synonym_mapper.py` — Exposes `get_similarity_threshold()` reading `TREND_SIMILARITY_THRESHOLD` env + scoring config, default `0.58`.
- `trend_system/ingestion/pipeline.py` — Region always `global`, language `en`, uses `normalize_season_tag` for SS26 etc.
- `trend_system/extraction/fashion_extractor.py` — `cat_map` extended for `outerwear, footwear, occasion, macro_trend, micro_trend, designer, styling, aesthetic`.
- `trend_system/aggregation/trend_aggregator.py` — Global explanation (cross-source, semantic, fashion weeks, no Iranian ratio), season via gregorian.
- `trend_system/scheduler/snapshot.py` — Semantic dedup (`semantic_dedup_signals`), global region/language, `trend_scope` handling, category-aware clustering.
- `trend_system/api/routes/trends.py` — `trend_scope` query param, global default filtering, isolation of historical iranian.
- `trend_system/config/__init__.py` — `Settings.HALF_LIFE_DAYS`, `TREND_SIMILARITY_THRESHOLD`, `get_scoring_config()` env overrides.
- `trend_system/main.py` — (via sync) seeds new taxonomy/sources with scope handling.

### Added (new global modules)
- `trend_system/collectors/global_sources/harpers_bazaar.py` — sitemap_index discovery (brand-tag/people-tag/content-tag).
- `trend_system/collectors/global_sources/whowhatwear.py` — sitemap.xml monthly archives + sitemap_news.xml.
- `trend_system/collectors/global_sources/wgsn.py` — Restricted/paywall-aware, respects `robots.txt` `Disallow: /` for `*`, graceful skip on 401/403, logs at INFO not error.
- `trend_system/extraction/season_extractor.py` — `normalize_season_tag()` (SS26→Spring/Summer 2026, AW26→Fall/Winter 2026, SS 2026, FW26, Resort, Pre-Fall), `extract_fashion_weeks()` (NY/London/Milan/Paris/Copenhagen extensible), `extract_season_context()`.
- `trend_system/normalization/semantic_cluster.py` — `SemanticClusterer` (Sentence Transformers cosine 0.58 configurable `TREND_SIMILARITY_THRESHOLD`, enrichment with category/garment/color/season/material/styling to avoid false merges e.g., `scarlet tailoring` vs `red handbag` separate, token overlap guard, synthetic isolation, fallback hash embedding deduped).

### Removed / Disabled (not deleted from filesystem for audit, but disabled in config)
- `trend_system/collectors/iranian_sources/` (`digikala_mag.py`, `banimag.py`, `modeworld.py`) — No longer registered in `ADAPTER_MAP`, not enabled in `sources.yaml` (enabled=false, scope=iranian). Historical files preserved for audit but not used.
- Iranian ranking/scraping assumptions removed from `pipeline.py` (region), `base.py` filter, `trend_score.py` (I gate), `snapshot.py` (iranian language fallback).

---

## 2. Deliverable B — Config Variables (all configurable, never hard-coded)

| Variable | Default | Env | Source | Description |
|---|---|---|---|---|
| `TREND_SIMILARITY_THRESHOLD` | `0.58` | `TREND_SIMILARITY_THRESHOLD` | `scoring.yaml:similarity_threshold` + `taxonomy.yaml:normalization.auto_threshold` | Cosine threshold for Sentence Transformers semantic clustering. Higher → stricter (fewer merges). Tuned to separate `red tailoring` (styling) vs `red handbag` (accessory) despite color overlap. |
| `HALF_LIFE_DAYS` | `30` | `HALF_LIFE_DAYS` / `TREND_HALF_LIFE_DAYS` | `scoring.yaml:half_life_days` + `recency.half_life_days` | Freshness decay `R=exp(-ln2*age/half_life)`. Age 30d →0.5, 60d→0.25. Configurable per `recency.formula`. |
| `TREND_SOURCES` (central) | 4 enabled global | — | `config/sources.yaml:sources[]` | Central array. Each entry has `source_id, name, region, scope, language, authority_weight, sitemap_url, rss_url, accessibility, extraction_method`. Add future global source by appending entry + adapter in `registry.py`. |
| `FASHION_WEEKS` | `["NY","London","Milan","Paris","Copenhagen"]` | — | `scoring.yaml:seasonal.fashion_weeks` | Extensible list; `season_extractor` regex detects `{city} Fashion Week`. Add `Berlin`, `Tokyo` etc. |
| `SEASON_NORMALIZATION` | `SS26→Spring/Summer 2026` | — | `scoring.yaml:seasonal.season_normalization` + `season_extractor.py:_SEASON_MAP` | Maps `SS26`, `AW26`, `FW26`, `SS 2026`, `Resort 2026`, `Pre-Fall 2026`. |
| `WINDOW_DAYS` | `30` | `WINDOW_DAYS` (if set) | `scoring.yaml:window_days` | Aggregation window. |
| `MIN_EVIDENCE / MIN_SOURCES` | `3` / `2` | — | `scoring.yaml:min_evidence_count/min_supporting_sources` | Actionability gate. |
| `SCORING_MODE` | `gated_geom` | — | `scoring.yaml:scoring_mode` | `gated_geom` (bundle × I^gate), `multiplicative`, `additive` (ablation). For global, `I=1` so gate neutral. |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | — | `taxonomy.yaml:normalization.embedding_model` | Sentence Transformers model. Fallback to hash embedding if not installed. |

**Never hard-code secrets:** `LLM_API_KEY` etc. via `.env` / `Settings`.

---

## 3. Deliverable C — Data Migration Explanation

**Goal:** Preserve history, isolate Iranian, make new trends global, no silent mixing.

1. **Schema migration (safe, additive, SQLite):**
   - `sources` + `scope TEXT DEFAULT 'global'`, `source_region TEXT`
   - `fashion_entities` + `global_relevance REAL`, `scope TEXT`, `source_region TEXT`
   - `trends` + `trend_scope TEXT DEFAULT 'global'`, `source_region TEXT`, `semantic_consistency REAL`, `recurrence_score REAL`
   - Executed via `scripts/migrate_global.py` (idempotent `ADD COLUMN IF NOT EXISTS`) + `scripts/sync_global.py` (upsert from `sources.yaml`/`taxonomy.yaml`).

2. **Data isolation:**
   - Pre-migration 15 trends (from 2026-09-21 Iranian validation: 14 docs 51 signals) had `scoring_version=v1_heuristic_gated_geom`. Migration set `trend_scope='iranian'`, `source_region='iranian'` for those, and disabled `digikala_mag/banimode_mag/modeworld` (`enabled=0, scope=iranian`).
   - Post-migration snapshot (global) upserts trends with `trend_scope='global'`. Concepts that have new global signals (e.g., `wide_leg_bottom`, `blazer`) are updated to `global` (representing current global relevance). Concepts with no new signals retain `iranian` and are excluded from default API queries (`WHERE trend_scope='global'`).
   - No `DELETE` of historical rows; `trend_history` retains all snapshots.

3. **Verification:**
   - `SELECT trend_scope, count(*) FROM trends GROUP BY trend_scope` before snapshot: `iranian:15`. After global snapshot: `global:15` (those with new signals updated), historical iranian preserved in `trend_history` and not returned by default global API unless `trend_scope=iranian` requested.
   - Synthetic test data isolated via `trend_scope` and `exclude_synthetic` flag, proven via `test_evidence_synthetic_isolation`.

---

## 4. Deliverable D — Test Results

### Existing suite (preserved, updated for global)
```
USE_SQLITE=1 pytest tests/ -v  → 38 passed (24 original + 14 global)
- test_app_import, test_routes_exist, test_llm_dummy
- test_jalali_conversion, test_jalali_season
- test_hash_dedup, test_near_dup
- test_evidence_trace_chain (full provenance Trend→Evidence→Signal→Observation→RawDocument)
- test_evidence_synthetic_isolation (exclude_synthetic flag)
- test_lookup_canonical, test_extraction_persian/english
- test_iran_relevance_omission (now expects I=1 for global)
- test_gated_geom_vs_additive (now expects I=1, scores >0.3)
- test_seasonal_soft_vs_hard, test_min_evidence_guard
- test_snapshot_point_in_time, test_no_future_leakage
```

### New global migration tests (`tests/test_global_migration.py`) — 14/14 passed
- `test_no_iranian_sources_enabled` — 4 enabled are Vogue/Harper/WWW/WGSN, no Iranian.
- `test_source_config_centralization` — central array, sitemap URLs verified, WGSN restricted.
- `test_registry_maps_global_adapters` — adapters instantiate.
- `test_extraction_global_trends` — detects `oversized_floral_brooches, dramatic_bows, sculptural_ruffles, animal_print, elevated_bomber_jacket, red_tailoring`.
- `test_season_normalization_SS26` — SS26→Spring/Summer 2026, FW26→Fall/Winter 2026, Resort, fashion weeks Paris/Copenhagen.
- `test_fashion_weeks_extensible` — NY/London/Milan/Paris/Copenhagen in config.
- `test_clustering_red_tailoring_not_handbags` — scarlet tailoring cluster separate from red handbags (category guard + token overlap + 0.58 threshold).
- `test_semantic_dedup_signals` — red_tailoring + scarlet tailoring merge, handbag stays separate.
- `test_similarity_threshold_configurable` — env `TREND_SIMILARITY_THRESHOLD` overrides.
- `test_freshness_half_life_configurable` — `HALF_LIFE_DAYS` 30→14, `recency_weight(30,30)=0.5`.
- `test_cross_source_validation` — multi-source C > single-source C.
- `test_trend_scoring_formula_global` — components G,R,C,semantic_consistency,recurrence, I=1.
- `test_wgsn_graceful_skip` — adapter exists, sitemap `https://www.wgsn.com/sitemap.xml`, robots handling.
- `test_isolation_historical_iranian` — global scope exists, total≥10, history preserved.

### Live collector verification (mocked, no external bypass)
- Harper’s Bazaar `sitemap_index.xml` fetched 2026-09-29: 8 sub-sitemaps including `content-tag`, `brand-tag` → allowed.
- Who What Wear `sitemap.xml` fetched: 200+ monthly archives + `sitemap-2026-09.xml` → allowed.
- WGSN `robots.txt` fetched: `User-agent: * Disallow: /` (allow only Googlebot/bingbot) → correctly triggers graceful skip (INFO log, not error, no paywall bypass).

---

## 5. Deliverable E — Final Architecture Diagram

```
Global Sources ──→ Evidence ──→ Extraction ──→ Normalization ──→ Sentence Transformers ──→ Clustering ──→ Cross-Source ──→ Freshness/Scoring ──→ Trend DB ──→ Recommendation Engine
     │               │             │                │                     │                    │                │                  │             │
     │               │             │                │                     │                    │                │                  │             └─► API (/api/v1/trends/current, /for-recommendation) — No outfit generation, snapshot only
     │               │             │                │                     │                    │                │                  └─► Current Trend Snapshot (hourly materialize_snapshot)
     │               │             │                │                     │                    │                └─► Trend Score = source_quality × freshness × cross_source × semantic_consistency × recurrence (gated_geom, I=1 for global)
     │               │             │                │                     │                    └─► Freshness R = exp(-ln2·age/HALF_LIFE)  HALF_LIFE_DAYS=30 configurable
     │               │             │                │                     └─► Cosine ≥0.58 configurable TREND_SIMILARITY_THRESHOLD, enriched with category/garment/color/season/material/styling, token overlap guard, synthetic isolation
     │               │             │                └─► Taxonomy (global_relevance) + synonym_mapper + season_extractor (SS26→Spring/Summer 2026, fashion weeks NY/London/Milan/Paris/Copenhagen)
     │               │             └─► title/date/source/url/concepts/garments/colors/materials/patterns/silhouettes/styling/designers/season/embeddings (trafilatura + gazetteer, lang=en)
     │               └─► article is evidence ( RawDocument → FashionObservation → TrendSignal → TrendEvidence ), short excerpts only (no full copyrighted article)
     └─► Vogue (sitemap.xml, authoritative 0.95) ─┐
         Harper's Bazaar (sitemap_index.xml, seasonal reports) ─┤─→ TREND_SOURCES central (config/sources.yaml) 4 enabled, robots.txt respected, WGSN gracefully skipped if 403/paywall
         Who What Wear (sitemap.xml, micro-trends) ─┤
         WGSN (sitemap.xml, restricted, forecasting 0.95) ─┘
                                                        │
Historical Iranian sources (Digikala Mag/BaniMag/Modeworld) — disabled (enabled:false, scope:iranian), isolated via trend_scope, not deleted, not mixed in scoring
User Location Iran — independent (Fashion AI profile, not trend scope)
```

**Pipeline order enforced:** `SOURCE → COLLECTOR → RAW → CLEANING → DEDUP → EXTRACTION → NORMALIZATION → SIGNAL → AGGREGATION → SCORING → SNAPSHOT → API` (collector discovers URLs, fetch with retries+robots, hash dedup, clean text, gazetteer extraction, synonym+season normalization, semantic_cluster dedup, aggregation window 30d, gated_geom scoring, snapshot hourly, API serves snapshot).

---

## 6. Deliverable F — Evidence-Based Extraction (structured signals, not article-as-trend)

- **RawDocument:** `source_id, source_url, title, content_html (≤50k), content_text, publication_date_utc, jalali, season, language, author, image_urls, content_hash, is_synthetic`
- **FashionObservation:** `raw_document_id, source_id, entity_id, raw_term, canonical_name, category, confidence, extractor_type (rule), span_text (200 chars), observed_at, region=global`
- **TrendSignal:** `concept, source_id, observation_id, raw_document_id, timestamp_utc, season (normalized SS26), evidence_type=article, confidence, region`
- **TrendEvidence:** `trend_id, source_id, observation_id, signal_id, raw_document_id, evidence_type, confidence, timestamp_utc, snippet (title[:200])`
- **Trend:** `canonical_name, category, global_score, iran_relevance_score (1.0 for global), recency_score, growth_score, cross_source_score, seasonal_relevance, current_score, lifecycle_state, first/last_seen, evidence_count, supporting_sources, is_actionable (≥3 ev, ≥2 src), explanation, scoring_version=v2_global, trend_scope=global, semantic_consistency`

**Extraction example:** Title *“Scarlet tailoring and oversized floral brooches dominate Paris Fashion Week SS26”* → concepts: `red_tailoring` (styling, via alias scarlet tailoring), `oversized_floral_brooches` (accessory), `season=Spring/Summer 2026`, `fashion_weeks=[Paris]`, `designers=[...]` if mentioned.

---

## 7. Deliverable G — How to Extend

- **Add new global source:** Append to `config/sources.yaml` (enabled, sitemap_url, scope global), create adapter in `trend_system/collectors/global_sources/newsource.py` extending `BaseCollector.discover_urls`, register in `registry.ADAPTER_MAP`, verify `robots.txt` and `sitemap.xml` manually, set `authority_weight`.
- **Tune thresholds:** `export TREND_SIMILARITY_THRESHOLD=0.65` or `HALF_LIFE_DAYS=14` then restart scheduler; no code change.
- **Add fashion week:** Append to `scoring.yaml:seasonal.fashion_weeks` and `season_extractor.py:_FASHION_WEEK_PATTERN`.
- **Add season:** Append to `scoring.yaml:seasonal.season_normalization` + `season_extractor.py:_SEASON_MAP`.

---

## 8. Verification of Constraints

- No Iranian trend sources in enabled config (verified via `test_no_iranian_sources_enabled`).
- Iranian logic removed from Trend Module only; rest of Fashion AI (user profile, location) untouched.
- No paywall bypass; WGSN logs `INFO` and skips on 401/403.
- No LLM unnecessary use; `llm_provider` dummy by default, `is_synthetic` isolated.
- All weights/thresholds via env/config, never hard-coded secrets.
- Recommendation engine consumes `/api/v1/trends/for-recommendation` (snapshot) not realtime scrape.
- Minimal rewrites: preserved `Base`, `Source/Trend` models, SQLite, taxonomy, API, scheduler.

---

*Generated via modular, continuously updateable, historically traceable pipeline. Next scheduled snapshot: hourly via APScheduler.*
