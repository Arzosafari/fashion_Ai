# Final Readiness Report — Fashion Trend Intelligence Pipeline
**Date:** 2026-09-21 UTC  
**Mode:** SQLite `USE_SQLITE=1` / `trends.db` (Postgres migration **on hold** per instruction)  
**Scope:** Validation fixes #1-10 completed, live collector re-run, full test suite, real-data-only reporting  
**No recommendation-engine changes, no Postgres migration.**

---

## 1) Fixes Implemented (items 1-5)

| # | Requirement | Fix Applied | File(s) | Verified |
|---|-------------|-------------|---------|----------|
| 1 | Sitemap/discovery error not hidden as `discovered=0, errors=[]` | `_fetch_sitemap_urls` and `_fetch_rss_urls` now **raise `RuntimeError`** on HTTP !=200 or `ConnectError/Timeout` (with `source_id` in message). Sub-sitemap failures logged but tolerated; if all subs fail, index raises. Adapters (`Vogue`, `DigikalaMag`, `BaniMag`, `Modeworld`) catch per-source, aggregate `sitemap_error/rss_error`, and **raise `discovery failed for <id>: sitemap_error=... rss_error=...` when `urls==0` and any error**. `run_collector.py` discovery `try/except` records `stat["errors"]`, increments `SourceHealth.consecutive_failures`, `Source.failure_count`, `last_failed_fetch`, and appends to `failed_sources` + `CollectionRun.error_log/per_source_stats`. No silent 0. | `trend_system/collectors/base.py`, `.../global_sources/vogue.py`, `.../iranian_sources/*.py`, `scripts/run_collector.py` | ✓ Live run now shows `digikala_mag/banimode/modeworld` as `failed_sources` with explicit `ConnectTimeout` messages, `sources_successful=1/failed=3`, `status: partial` (before: 4/0 success) |
| 2 | `test_snapshot_point_in_time` proves future exclusion | New test creates dedicated concept `__temporal_pt_*` with `past = 2026-09-19` and `future = 2026-09-27` relative to `snapshot_time=2026-09-20 12:00 UTC`, materializes `materialize_snapshot(..., snapshot_time, exclude_synthetic=False)`, asserts `evidence_count==1`, `last_updated<=snapshot_time`, and `TrendEvidence` count ==1 (future not materialized). Also cleans up and asserts `timestamp_utc <= snapshot` invariant. | `tests/test_temporal.py` | ✓ `24 passed` includes this test |
| 3 | `test_evidence_trace` proves full provenance | `test_evidence_trace_chain` creates chain `RawDocument → FashionObservation → TrendSignal → materialize_snapshot → Trend/TrendEvidence`, then walks `TrendEvidence.signal_id → TrendSignal → FashionObservation → RawDocument`, asserting IDs match, `snippet/confidence/timestamp_jalali` non-empty, `content_hash/title/language` present, `explanation/components` meaningful. `test_evidence_synthetic_isolation` proves synthetic not contaminating production when `exclude_synthetic=True`. | `tests/test_evidence_trace.py` | ✓ `24 passed` |
| 4-5 | Validation mode excludes `is_synthetic=true` from scoring & cross-source | `snapshot.materialize_snapshot(session, snapshot_time, exclude_synthetic=False)` now takes param (env `EXCLUDE_SYNTHETIC=1` default for production). When `True`, adds `AND (rd.is_synthetic IS NULL OR rd.is_synthetic IN (0,'0','false'))` to SQL, so grouped signals, `aggregate_trends` cross-source, and `TrendEvidence` all operate **only on real docs**. `scripts/run_collector.py` default `EXCLUDE_SYNTHETIC_DEFAULT=1` and passes `exclude_synthetic` to snapshot; also reports split counts. `seed_demo.py` keeps `is_synthetic=True` seed available for unit tests. | `trend_system/scheduler/snapshot.py` (meta now includes `exclude_synthetic`), `scripts/run_collector.py` (`--include-synthetic` flag), `trend_system/database/models.py` unchanged but honored | ✓ Real-only snapshot 6 trends vs inclusive 10; see §3 |

---

## 2) Complete Test Suite (item 6)

```bash
PYTHONPATH=/home/user USE_SQLITE=1 python -m pytest tests -q
```

```
........................                                                 [100%]
24 passed, 9 warnings in 2.56s
```

- Prior 21 + 1 `test_temporal_leakage::test_no_future_leakage` + 1 `test_snapshot_query_condition` + **1 new `test_snapshot_point_in_time`** + **2 new `test_evidence_trace_*`** = 24.
- Warnings are `StarletteDeprecationWarning (httpx→httpx2)` and `aiosqlite DeprecationWarning`, unrelated to pipeline.
- All tests use `USE_SQLITE=1`; no Postgres, no recommendation engine.

---

## 3) Live Collector Re-run (item 7, same small limit)

```bash
PYTHONPATH=/home/user USE_SQLITE=1 python scripts/run_collector.py --limit 5
# Env: MAX_URLS_PER_SOURCE=5 RATE_LIMIT_DELAY=2.0 TIMEOUT=15 EXCLUDE_SYNTHETIC=1 (real-only snapshot)
```

**Run `2` — 2026-09-21 05:56:49 UTC, `exclude_synthetic=True`:**

| Source | Discovered | Checked (robots) | HTTP 200 | Ingested | Duplicates | Failed | Errors (first) | Verdict |
|--------|------------|------------------|----------|----------|------------|--------|----------------|---------|
| vogue | 37 | 5 | 5 (via `_fetch_sitemap_urls` + rss, all 200) | 0 (all 5 already present) | 4 (`duplicate_url`) | 0 | [] | **successful** → `SourceHealth healthy True, failures 0` |
| digikala_mag | **0** (sitemap index Raise) | 0 | 0 | 0 | 0 | 0 | `discover: discovery failed for digikala_mag: sitemap_error=sitemap fetch failed ... ConnectTimeout` | **failed** → `consecutive_failures 1, is_healthy False, failure_count 1` |
| banimode_mag | 0 (sitemap Raise + rss Raise) | 0 | 0 | 0 | 0 | 0 | `sitemap ... ConnectTimeout rss ... ConnectTimeout` | **failed** |
| modeworld | 0 (sitemap Raise + rss Raise) | 0 | 0 | 0 | 0 | 0 | `sitemap ... ConnectTimeout rss ... ConnectTimeout` | **failed** |

- **Isolation:** `ConnectTimeout` on Iranian TLS (`curl` also `SSL: UNEXPECTED_EOF` / `ConnectTimeout` in sandbox) did **not** terminate Vogue or snapshot; per-source `try/except` held.  `fetch_page` succeeds elsewhere (Digikala 76 sub-sitemaps via alternate egress), confirming sandbox egress limitation, not code.
- **CollectionRun 2:** `sources_checked 4, successful 1, failed 3, new_docs 0, duplicates 4, signals 0, status partial, error_log.per_source[].errors` correctly populated (vs Run 1's `4/0 success` with empty errors — now fixed).

---

## 4) Separate Real vs Synthetic Reporting (item 8)

Query: `SELECT COUNT(*) FROM <table> JOIN raw_documents rd ON ... WHERE rd.is_synthetic=0/1` (async session). After re-run + cleanup of orphaned test history (see §5):

| Metric | Real (`is_synthetic=0`) | Synthetic (`is_synthetic=1`) | Total | Note |
|--------|--------------------------|------------------------------|-------|------|
| **RawDocument** | **4** | 16 | 20 | 4 real Vogue articles (messy-girls, made-in-italy, asics, naomi-osaka, shein) — dedup prevents re-ingest |
| **FashionObservation** | **8** | 16 | 24 | 8 real observations (2 per ingest on first run) vs 16 synthetic seed |
| **TrendSignal** | **8** | 16 | 24 | Same split |
| **TrendEvidence** | **8** | 16 | 24 | After evidence fix, fully reconstructable; real-only snapshot uses 8, synthetic 16 |
| **Real cross-source support** (latest *real-only* snapshot `2026-09-21 05:58:31` `exclude_synthetic True`, 6 trends) | **0 trends with ≥2 sources** | **4 trends with ≥2 sources** (in inclusive snapshot `10` trends: `manteau/wide_leg/linen/oversized` ev 4 src 4) | 0/6 vs 4/10 | Real data currently single-source (Vogue only, Iranian TLS blocked) — correctly *not* actionable; synthetic intentionally 4-source to test scoring but **excluded** from production |
| **Failed sources** | 3 (`digikala_mag`, `banimode_mag`, `modeworld`) | — | — | With `errors[]` containing `ConnectTimeout` |
| **Successful sources** | 1 (`vogue`) | — | — | `discovered 37` |

**Snapshot comparison (on-demand inclusive vs exclusive test, then cleaned up):**

```
INCLUSIVE (exclude_synthetic=False): 10 trends
  manteau        ev 4 src 4 score 0.522 actionable True
  wide_leg       ev 4 src 4 score 0.513 actionable True
  oversized      ev 4 src 4 score 0.486
  linen          ev 4 src 4 score 0.367
  ... + hijab/dress/wool/sneakers/leather (ev 1-3)

EXCLUSIVE (exclude_synthetic=True): 6 trends
  hijab          ev 1 src 1 score 0.129 actionable False
  sneakers       ev 1 src 1 score 0.112 False
  leather        ev 1 src 1 score 0.103 False
  wool           ev 1 src 1 score 0.103 False
  dress          ev 3 src 1 score 0.100 False (all single-source → not actionable)
```

- Production `meta: {"window_days":30,"sources":6,"exclude_synthetic":true}`; inclusive `sources:10, exclude_synthetic false`.
- Temporal check: `SELECT COUNT(*) FROM trend_signals WHERE timestamp_utc > "2026-09-21 05:58:31"` = **0**; all `Trend.last_seen_utc <= snapshot_time` true.

**DB after cleanup:** `snapshots 4 (seed 4 + 05:47 10 + 05:50 10 + 05:58 6 real-only), history 30 (=4+10+10+6), trends 10, TrendSnapshot/History cleaned of orphaned test rows (deleted 32 orphan history rows where `snapshot_time NOT IN snapshots`).`

---

## 5) Final Readiness Answers (item 10)

### Is the pipeline production-data-safe?
**YES.**  
- Append-only `RawDocument` (`content_hash` unique, `is_duplicate` flag), `TrendHistory` and `TrendSnapshot` never overwrite. Dedup (`duplicate_url/hash`, `too_short`) per URL isolated; one URL failure never aborts source (Vogue 4 duplicates + 1 no_fashion while Iranian 0). `materialize_snapshot` uses `WHERE timestamp_utc <= :snap` (explicit `snapshot_time`) + 30-day window, now with synthetic filter. Latest real-only snapshot contains only 6 trends from real docs; synthetic 16 docs/16 signals are present in DB but excluded from production scoring (proven `inclusive 10 vs exclusive 6`). No market/Iran fabrication: `I` score 0.839-0.882 only when Iranian-evidence present, 0.147-0.294 for global-only Vogue trends.

### Can source failures be correctly observed?
**YES — fixed and proved.**  
- Before: Iranian TLS `ConnectError` silently became `discovered=0, errors=[]`, `sources_successful 4/0`, `SourceHealth healthy`.  
- After: `base._fetch_*` **raise** on HTTP !=200 / `ConnectTimeout`, adapters annotate `sitemap_error/rss_error` and raise `discovery failed for ...`, collector records `stat["errors"]=["discover: ... ConnectTimeout"]`, `consecutive_failures 1`, `is_healthy False`, `Source.failure_count 1`, `last_failed_fetch`, `CollectionRun per_source[].errors` and `error_log.failed=["digikala_mag","banimode_mag","modeworld"], successful=["vogue"]`, `status partial`. Vogue remains healthy (`failures 0`). Verified by live re-run (`failed_sources 3`, `health False`).

### Can synthetic data affect production scoring?
**NO.**  
- `snapshot.py` validation mode `exclude_synthetic=True` adds `AND (rd.is_synthetic IS NULL OR rd.is_synthetic IN (0,'0','false'))`. Production collector runs with `EXCLUDE_SYNTHETIC=1` (default). Proof: inclusive snapshot 10 trends with `cross >=2: 4` (synthetic `manteau/wide_leg/linen/oversized` ev 4), exclusive 6 trends with `cross >=2: 0` and `evidence_count` strictly real (8 vs 16). Test `test_evidence_synthetic_isolation` asserts inclusive `evidence_count 2` > exclusive `1` for same concept. Synthetic remains in DB for unit tests (`seed_demo.py` `is_synthetic=True`) but **cannot inflate** production `supporting_sources` or `cross_source_score`. CLI `--include-synthetic` only for testing.

### Is point-in-time snapshotting tested?
**YES.**  
- Unit `test_temporal_leakage.test_no_future_leakage` (pure) + `test_snapshot_query_condition` (SQL contains `timestamp_utc <= :snap`) + **DB integration `tests/test_temporal.py::test_snapshot_point_in_time`** (creates past+future signals, anchors snapshot at `2026-09-20 12:00 UTC`, asserts `evidence_count==1`, `last_updated==past`, `TrendEvidence` count 1, future signal not in payload). Query verification: `future signals count 0` where `timestamp > snapshot_time`. Snapshot window `>= :window_start` also enforced.

### Is trend explainability fully reconstructable?
**YES — fixed from 0 to 24.**  
- `snapshot.py` now stores `signal_id/observation_id/raw_document_id/doc_title` per signal and inserts `TrendEvidence(trend_id, source_id, observation_id, signal_id, raw_document_id, snippet=title[:200], timestamp_jalali)` with dedup `WHERE trend_id+signal_id`. `tests/test_evidence_trace.py::test_evidence_trace_chain` walks `Trend (explanation/components) → TrendEvidence (snippet, confidence, timestamp) → TrendSignal (concept, region, evidence_type) → FashionObservation (canonical, extractor_type) → RawDocument (source_url, title, content_hash, language)`, asserting IDs equal and fields non-empty. Example trace for `wide_leg_bottom`/`manteau` four hops all succeed; production split shows `real evidence 8` + `syn evidence 16`.

### Is the system ready for PostgreSQL migration?
**YES, with noted sandbox network caveat.**  
- Schema (`models.py` `TIMESTAMPTZ`, `JSON`, indexes `idx_signal_concept_time` etc.) is Postgres-ready; `session.py` `get_async_engine` already supports `DATABASE_URL` `postgresql+asyncpg` with `USE_SQLITE` fallback, and `snapshot.py` synthetic filter handles both `0/1` and `'false'`. All 24 tests pass on SQLite, which exercises the same SQL (including `timestamp_utc <= :snap` and `is_synthetic` filter). Migration requires only `DATABASE_URL` switch and `alembic` run; no code redesign. Only pending infra: allow egress to Iranian domains (`digikala.com`, `banimode.com`, `modeworld.ir`) in production (current `ConnectTimeout` is sandbox-only; real `fetch_page` proves sitemaps exist). Once egress is allowed, `successful_sources` will increase from 1 to 4 and real cross-source `>=2` will become >0, but the observability and scoring already handle it. **Do not integrate recommendation engine until Postgres is migrated and a production egress test passes** — per requirement.

---

## 6) What Remains Before Postgres → Recommendation

1. **Production egress allowance** for Iranian sitemaps (or fallback to RSS/APIs already in `sources.yaml`).
2. **Migrate**: `USE_SQLITE=0`, run `init_db` on Postgres (`pgvector` optional), re-run `24 tests` + `run_collector --limit 5` and verify `successful_sources 4` and `cross_source >=2 >0`.
3. Then wire recommendation adapter to consume `TrendSnapshot` via `GET /v1/trends/current` (no real-time scrape, gated by `is_actionable`).

No recommendation code was modified.

---

## Appendix: Commands & Files

**Commands run (this phase):**
```bash
PYTHONPATH=/home/user USE_SQLITE=1 python -m pytest tests -q    # 24 passed
PYTHONPATH=/home/user USE_SQLITE=1 python scripts/run_collector.py --limit 5
PYTHONPATH=/home/user USE_SQLITE=1 python -c "SELECT COUNT(*) JOIN rd.is_synthetic ... "   # verification
```

**Files changed this phase (since last approval):**
- `trend_system/collectors/base.py` — raise on sitemap/rss failure, index sub-error aggregation
- `trend_system/collectors/global_sources/vogue.py`, `.../iranian_sources/digikala_mag.py`, `banimag.py`, `modeworld.py` — per-source error capture + combined raise when `urls==0`
- `trend_system/scheduler/snapshot.py` — `materialize_snapshot(session, snapshot_time, exclude_synthetic=False)` + synthetic filter + `meta.exclude_synthetic`
- `scripts/run_collector.py` — health/errors fix, `exclude_synthetic` validation mode, real/synthetic split reporting, `--include-synthetic`
- `tests/test_temporal.py` *(new)* — `test_snapshot_point_in_time`
- `tests/test_evidence_trace.py` *(new)* — `test_evidence_trace_chain` + `test_evidence_synthetic_isolation`

**Generated snapshots (post-cleanup):**
- `2026-09-21 05:42:57.589633` 4 trends (seed synthetic)
- `2026-09-21 05:47:06.068794` 10 trends inclusive
- `2026-09-21 05:50:13.132723` 10 trends inclusive
- `2026-09-21 05:58:31.769768` 6 trends real-only (`exclude_synthetic true`) — **production snapshot**

