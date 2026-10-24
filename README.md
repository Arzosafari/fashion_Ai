# Fashion AI — Voice/Text Understanding, Weather & Global Fashion Trends

An integrated Fashion AI application with three cooperating modules:

1. **Request Understanding** — real-time English speech-to-text (Vosk), a
   fashion lexicon, typed or spoken requests, multi-turn follow-ups, and a
   validated structured `FashionRequestOutput`.
2. **Weather Context** — independent, validated Open-Meteo current/forecast
   context (`WeatherContext`) with caching and graceful degradation.
3. **Global Fashion Trend Intelligence** — collection from global editorial
   sources (Vogue, Harper's Bazaar, Who What Wear, WGSN when legally
   accessible), raw-document ingestion, fashion-observation extraction,
   taxonomy normalization, Sentence-Transformers semantic clustering,
   cross-source validation, freshness/seasonality scoring, evidence
   provenance and point-in-time snapshots.

The modules stay decoupled: the trend module can run standalone, and the
voice/text + weather pipeline keeps working even if the trend database or its
dependencies are unavailable.

```
User voice / typed request
        │
        ▼
Request understanding + feature extraction  ──►  FashionRequestOutput
        │                                             │
        │                                             ├──► WeatherContext (independent)
        │                                             └──► TrendContext   (independent)
        ▼
RecommendationContext  ──►  (future) Recommendation Engine
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# existing voice/text + weather + trend API (integrated app)
python run_server.py                     # http://localhost:8000
# or
uvicorn fashion_stt.server:app --host 0.0.0.0 --port 8000

# trend module only (same routers, standalone)
uvicorn trend_system.main:app --host 0.0.0.0 --port 8001
```

The first voice request downloads the Vosk model into `models/` (requires
network access). The trend module uses the existing SQLite database
`trends.db` and never requires PostgreSQL.

### Operating the trend pipeline

```bash
# seed / refresh reference data (idempotent, never deletes trend data)
python scripts/seed_sources.py

# collect → ingest → snapshot (respects robots.txt; WGSN skipped when blocked)
python scripts/run_collector.py

# materialize a snapshot from existing evidence
python scripts/materialize_snapshot.py

# optional: offline demo data (synthetic, excluded from production snapshots)
python scripts/seed_demo.py
```

Background scheduling is **opt-in and off by default**; the API never starts a
scheduler, so no duplicate recurring jobs are registered:

```bash
TREND_SCHEDULER_ENABLED=1 python scripts/schedule_trends.py
```

## API

### Integrated app (`fashion_stt.server`)

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/health` | Module status (request understanding, weather, trends) |
| POST | `/api/understand` | Voice/typed request → structured features + weather + trend context |
| GET  | `/api/weather` | Standalone weather context |
| POST | `/api/weather/resolve` | Validate relayed Open-Meteo payloads |
| POST | `/api/transcribe` | Audio file → transcript + entities |
| WS   | `/ws/transcribe` | Real-time PCM streaming |
| GET  | `/api/catalog`, `/api/extract`, `/api/tts` | Existing utilities |
| GET  | `/api/v1/trends/*`, `/api/v1/sources/*` | Global trend module (see below) |

### Trend module

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/v1/trends/current?limit=&category=&lifecycle=&trend_scope=` | Latest materialized snapshot |
| GET  | `/api/v1/trends/for-recommendation?limit=&season=` | Actionable trends, ranked (for the recommendation engine) |
| GET  | `/api/v1/trends/context?limit=` | Compact, documented context used by the request pipeline |
| GET  | `/api/v1/trends?q=&category=&lifecycle=&sort=&order=&limit=` | Trend table query |
| GET  | `/api/v1/trends/by-name/{canonical}` | Trend + top evidence snippets |
| GET  | `/api/v1/trends/history/{trend_id}?from_date=&to_date=` | Historical scores |
| POST | `/api/v1/trends/refresh?limit=` | On-demand collect + snapshot |
| GET  | `/api/v1/sources`, `/api/v1/sources/{id}/health`, `/api/v1/sources/runs/history` | Source registry + health |
| GET  | `/health` | Standalone trend app health (port 8001) |

Example (`GET /api/v1/trends/for-recommendation?limit=1`, historical data):

```json
{
  "snapshot_time_utc": "2026-10-04T06:31:56.822584",
  "snapshot_time_jalali": "1405-07-12",
  "season": "autumn",
  "trends": [{
    "trend": "black",
    "canonical_name": "black",
    "category": "color",
    "trend_score": 0.6856,
    "current_score": 0.6856,
    "iran_relevance": 1.0,
    "global_strength": 0.9494,
    "lifecycle": "emerging",
    "confidence": 0.941,
    "evidence_count": 17,
    "supporting_sources": 2,
    "seasonal_relevance": 1.0,
    "growth": 1.2662,
    "is_actionable": true,
    "explanation": "black is emerging based on 17 signals ... Trend scope global ...",
    "components": {"G": 0.9494, "C": 1.6826, "C_norm": 0.8413, "P": 0.2, "R": 0.941,
                   "Gw": 1.2662, "Gw_norm": 0.974, "S": 1.0, "S_norm": 0.8333,
                   "I": 1.0, "semantic_consistency": 0.85, "recurrence": 0.2}
  }],
  "meta": {"scoring_version": "v2_global", "scoring_mode": "gated_geom", "total": 40}
}
```

Empty database / unavailable module responses are HTTP 200 with
`available: false` and `status: "no_snapshot" | "unavailable"`, so callers never
need to special-case failures.

## Trend scoring

`config/scoring.yaml` (all thresholds configurable, no hard-coded values):

```
G      = Σ(w·confidence·authority) / Σ(w)        source quality
R      = Σ(w)/n                                 freshness (w = 2^(-age/half_life))
C      = 1 + ln(1+distinct_sources) / ln(1+max_sources);  C_norm = C/2
P      = distinct_days / window_days            recurrence
Gw     = clamp(1+growth, 0.8, 1.3) / 1.3
S      = seasonal_affinity / 1.2
I      = 1.0                                    neutral gate (global scope)

score  = exp( Σ w_k·ln(x_k) / Σ w_k ) · I^gate   (gated geometric mean)
x = {G, C_norm, P, R, Gw, S}
```

Freshness half-life (`HALF_LIFE_DAYS`, default 30) and clustering similarity
(`TREND_SIMILARITY_THRESHOLD`, default 0.58) are environment-configurable. The
implementation reproduces the historical snapshots in `trends.db` (37/40 trend
scores within 0.01 of the original; mean Δ 0.002).

## Sources and compliance

| Source | Enabled | Access | Notes |
|--------|---------|--------|-------|
| Vogue (`vogue`) | ✅ | public | sitemap + RSS |
| Harper's Bazaar (`harpers_bazaar`) | ✅ | public | `sitemap_index.xml` |
| Who What Wear (`whowhatwear`) | ✅ | public | `sitemap.xml` monthly archives |
| WGSN (`wgsn`) | ✅ (restricted) | paywall / `robots.txt` disallows `*` | adapter exists and is **skipped gracefully**; no bypass |
| Business of Fashion, ELLE, Google/Pinterest trends | ⛔ disabled | — | kept for extensibility |

Collection respects `robots.txt`, rate limits (`RATE_LIMIT_DELAY`), timeouts and
retry limits, and stores only short evidence snippets — never full copyrighted
articles. Iranian source adapters and historical rows are retained for audit but
are **not enabled** in the global pipeline (`trend_scope=global`).

## Configuration

Copy `.env.example` → `.env` for overrides. Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:///<repo>/trends.db` | Trend database (SQLite default) |
| `SYNC_DATABASE_URL` | `sqlite:///<repo>/trends.db` | Sync tools/scripts |
| `HALF_LIFE_DAYS` | `30` | Freshness half-life |
| `TREND_SIMILARITY_THRESHOLD` | `0.58` | Semantic clustering threshold |
| `WINDOW_DAYS` | `30` | Scoring/evidence window |
| `EXCLUDE_SYNTHETIC` | `1` | Exclude synthetic seed docs from snapshots |
| `TREND_SCHEDULER_ENABLED` | `0` | Opt-in background scheduler |
| `LLM_ENABLED` / `LLM_PROVIDER` / `LLM_API_KEY` | `false` / `dummy` / — | Optional extraction provider; never commit keys |
| `WEATHER_*` | Open-Meteo defaults | Existing weather module |

Other config files: `config/scoring.yaml`, `config/taxonomy.yaml`,
`config/sources.yaml`, `config/seasonal_affinity.yaml`, `config/llm.yaml`.

## Sentence-Transformers embeddings

Semantic clustering uses `paraphrase-multilingual-MiniLM-L12-v2` when
`sentence-transformers` + `torch` are installed:

```bash
pip install -e ".[embeddings]"
```

Without them, the module falls back to deterministic hash embeddings plus a
synonym-aware lexical guard (same API, no external dependency). Category guards
prevent false merges such as *red tailoring* (styling) ↔ *red handbag*
(accessory).

## Data safety

* `trends.db` is preserved; schema evolution uses additive
  `ALTER TABLE … ADD COLUMN` only (no drops, no destructive migrations).
* Snapshots/history/evidence are append-only; re-materializing the same
  timestamp is idempotent.
* `pytest` runs against a temporary copy of `trends.db` (see
  `tests/conftest.py`), so tests never modify the historical database.
* Secrets belong in `.env` (git-ignored); `.env.example` contains placeholders.

## Testing

```bash
pytest -q                        # full suite (offline: 84 passed; voice WER tests
                                 # need the Vosk model download and internet)
pytest tests/test_trend_integration.py -q
pytest tests/test_global_migration.py tests/test_temporal.py tests/test_evidence_trace.py -q
```

Network-dependent voice tests are skipped/failed gracefully when the Vosk model
cannot be downloaded. Live collection from vogue.com etc. requires outbound
network access; it is intentionally not exercised by the test-suite.

## Documentation

* `FASHION_TREND_INTELLIGENCE_ARCHITECTURE*.md` — original architecture,
  data flow and scoring rationale.
* `GLOBAL_MIGRATION_REPORT.md`, `VERIFICATION_REPORT.md`,
  `FINAL_READINESS_REPORT.md` — historical validation of the trend module.

## License

Research prototype — respect robots.txt, rate limits and source terms.
