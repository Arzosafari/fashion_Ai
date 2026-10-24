# Fashion Trend Intelligence Pipeline — MVP

**For Iranian Market Recommendation System** — Final Architecture Rev 3, 4 MVP sources: **Vogue, Digikala Mag, BaniMag, Modeworld**.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# set DATABASE_URL (Postgres) or leave default for local

# init DB + seed
python scripts/seed_sources.py

# manual collect (discover URLs)
python scripts/run_collector.py

# materialize snapshot (hourly job does this automatically)
python scripts/materialize_snapshot.py

# run API + scheduler
uvicorn trend_system.main:app --host 0.0.0.0 --port 8000 --reload
# docs at http://localhost:8000/docs
```

## Architecture

See **FASHION_TREND_INTELLIGENCE_ARCHITECTURE_FINAL.md** for full data flow, source adapters, DB schema, six-component scoring (`G,C,P,R,I,Gw,S` gated geometric mean), seasonality (Persian calendar), Iran relevance (omission not estimation), evidence provenance, and recommendation boundary.

## API

- `GET /api/v1/trends/current?limit=20&category=garment&lifecycle=rising&region=iran`
- `GET /api/v1/trends/for-recommendation?season=summer&limit=10` ← **for Rec Engine**
- `GET /api/v1/trends/by-name/{canonical}`
- `GET /api/v1/trends/history/{trend_id}`
- `GET /api/v1/sources`
- `GET /health`

## Scoring

Default `scoring_mode: gated_geom` (bundle geometric mean × Iran gate). Switch via `config/scoring.yaml`:

```yaml
scoring_mode: multiplicative  # or additive, geometric, gated_geom
```

All weights in `config/scoring.yaml` and `config/seasonal_affinity.yaml` — no hard-coded thresholds.

## LLM

Provider-agnostic. Default `enabled: false` → DummyProvider, system works without key.

```yaml
# config/llm.yaml
llm:
  enabled: true
  provider: openai  # openai|anthropic|local|dummy
  model: gpt-4o-mini
  api_key_env: LLM_API_KEY
```

Or `LLM_ENABLED=false` in `.env`.

## Testing

```bash
pytest -v
pytest tests/test_temporal_leakage.py -v
```

## Sources

| ID | Status | Discovery |
|----|--------|-----------|
| vogue | enabled | sitemap + RSS |
| digikala_mag | enabled | sitemap |
| banimode_mag | enabled | sitemap + RSS |
| modeworld | enabled | sitemap |
| iranmodeling, fashion4iran, digistyle, google_trends, pinterest | disabled candidates |

## Calendars

Stored as `timestamp_utc` (primary) + `jalali_date` + `season` + `month` (both calendars). All scoring uses UTC only.

## License

Research prototype — respect robots.txt, rate limits, and source terms.
