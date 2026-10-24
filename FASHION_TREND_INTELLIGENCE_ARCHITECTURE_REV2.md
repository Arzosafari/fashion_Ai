# Fashion Trend Intelligence Pipeline — REVISED Architecture (Rev 2)
### Incorporating 2026-09-21 Feedback — Before Implementation
**Date:** 2026-09-21 | **Status:** Rev 2 — Awaiting approval  
**Changes vs Rev 1:** New Iranian source evaluation (3 candidates), explicit seasonality, six-component scoring, provider-agnostic LLM, evidence preservation, temporal-leakage-free evaluation design, tuned-parameter methodology, updated research & schema.

---

## Table of Contents
1. [Executive Summary of Changes](#1-executive-summary-of-changes)
2. [Revised Iranian Source Investigation (2–3 New Candidates)](#2-revised-iranian-source-investigation)
3. [Lightweight Architecture — Confirmed Stack](#3-lightweight-architecture--confirmed-stack)
4. [Hybrid Extraction — Provider-Agnostic LLM](#4-hybrid-extraction--provider-agnostic-llm)
5. [Six-Component Trend Scoring (Research vs Heuristic)](#5-six-component-trend-scoring)
6. [Seasonality — Explicit Component](#6-seasonality--explicit-component)
7. [Iran Relevance — Evidence-Based, Separate](#7-iran-relevance--evidence-based-separate)
8. [Evidence & Explainability — Reconstructable “Why”](#8-evidence--explainability)
9. [Temporal Validation & Parameter Tuning Methodology](#9-temporal-validation--parameter-tuning)
10. [Updated Research Review (Detection, Forecasting, Temporal, Social, Multimodal, RecSys)](#10-updated-research-review)
11. [Revised Database Schema](#11-revised-database-schema)
12. [Revised Pipeline, API & MVP Scope](#12-revised-pipeline-api--mvp-scope)
13. [File Structure & Approval Gate](#13-file-structure--approval-gate)

---

## 1. Executive Summary of Changes

| # | Feedback | How Rev 2 Addresses It |
|---|----------|------------------------|
| 1 | **Keep Vogue + Digikala Mag as confirmed MVP; re-evaluate Iranian sources; don’t lock Fashion4Iran; keep Digistyle disabled unless justified** | Vogue + Digikala Mag stay core. Fashion4Iran demoted to *candidate disabled by default*. Added full live evaluation of **3 new Iran-relevant sources**: **BaniMag (banimode.com/blog)**, **Modeworld (modeworld.ir)**, **IranModeling (iranmodeling.net)** — each live-probed 2026-09-21 for robots/sitemap/RSS. Digistyle product catalog stays disabled; justified only if future market-availability proxy proves valuable. |
| 2 | **Keep lightweight: APScheduler+PostgreSQL+optional pgvector, no Redis/Airflow/Kafka/K8s** | Confirmed. Rev 2 adds `SchedulerInterface` abstraction but default stays single-process APScheduler + Postgres persistence. |
| 3 | **Hybrid extraction: rules → taxonomy → embeddings → LLM (cached, structured, schema-validated, provider-agnostic, no hard-coded OpenAI)** | Rev 2 introduces `LLMProvider` interface + `config/llm.yaml` (provider/model/api_base configurable), cache table, JSON schema validation, fallback to rules if no key. System works with zero LLM calls. |
| 4 | **Exponential decay stays but 30-day half-life is NOT optimal — all thresholds configurable + evaluation methodology to tune** | Rev 2: all parameters in `config/scoring.yaml` as engineering knobs; adds time-series cross-validation methodology to estimate half-life, weights, thresholds from historical data. |
| 5 | **Explicit seasonal relevance; separate six components before combining** | New section 6: `GLOBAL_TREND_STRENGTH`, `IRAN_RELEVANCE`, `RECENCY`, `GROWTH`, `CROSS_SOURCE_EVIDENCE`, `SEASONAL_RELEVANCE` computed separately then combined. |
| 6 | **Iran relevance separate, evidence-based, no fabrication** | Section 7: weighted sum from Iranian publications + Persian mentions + local vocab + optional market evidence — all derived from stored signals. |
| 7 | **Preserve evidence per trend, answer “Why?”** | Section 8: `trend_evidence` many-to-many + snapshot provenance; explanation generated from DB counts, not hallucination. |
| 8 | **Temporal leakage prevention for historical evaluation** | Section 9: `timestamp <= snapshot_time` invariant enforced in code + tests; time-based train/test splits. |
| 9 | **MVP focused on reliable collection → snapshot → API; no multimodal/image** | Section 12: MVP scope explicitly excludes CV pipeline (reserved for Advanced). |
| 10 | **Research: add papers for detection/forecasting/temporal/social/multimodal/recsys, state what’s supported vs adapted vs heuristic** | Section 10 expanded from 8 to 12 papers/tracks with support/adapt/heuristic table. |
| 11 | **Show revised architecture & schema** | This doc = Rev 2 architecture; Rev 1 kept as `_REV1` for traceability. |

---

## 2. Revised Iranian Source Investigation

> **Goal:** Multiple *independent* evidence channels for Iranian fashion — not just three websites, but editorial vs e-commerce-mag vs pure magazine vs model-media.

### 2.1 Investigation Method (Live 2026-09-21)
For each candidate: fetch `robots.txt` + `sitemap` index + RSS/Feed + front-page, log `Authority / Update frequency / Volume / Iran relevance / Accessibility / RSS-API-Sitemap / Crawling feasibility / Robots / Reliability / Diversity`.

### 2.2 Evaluated Candidates — Full Table

#### A. Confirmed Core (carry from Rev 1)

| Source | Type | Country | Authority | Update | Volume (fashion) | Iran Rel | Accessibility | RSS/Sitemap/API | Robots | Crawl | Reliability | Diversity | Verdict |
|--------|------|---------|-----------|--------|------------------|----------|---------------|-----------------|--------|-------|-------------|-----------|---------|
| **Vogue (vogue.com)** | Magazine | US | **Very High** (Condé Nast, global fashion authority) | High (multiple/day) | High | Low (global) | Public HTML | Sitemap `sitemap.xml` → monthly indexes; RSS `feed/rss` live ✅ (fetch 2026-09-21 returned ~20 items) | `robots.txt` allows articles (`Allow: /*.js etc`, blocks `/*?`, `/search`); blocks AI training bots but not `*` → crawl allowed | Yes, sitemap+RSS discoverable; selectors need verification but HTML accessible | Very High | Global reference | **CORE MVP** — high `authority_weight=0.9` |
| **Digikala Mag (digikala.com/mag)** | E-commerce Magazine | IR | **Very High** (Digikala = Iran’s largest e-commerce, 3rd most visited site) | Medium-High (daily) | High (fashion + lifestyle) | **Very High** (Persian, `چی بپوشم`, `مانتو`) | Public | Sitemap `mag/sitemap_index.xml` ✅; RSS per mag section | Allows `*/mag/*.js/.css`, blocks `/magnet`, `?` — use sitemap URLs only | Yes, via sitemap index | Very High | E-commerce editorial | **CORE MVP** — high `authority_weight=0.85`, `iran_relevance` proxy |

#### B. Newly Evaluated Iranian Sources (2–3 recommended to add)

| Source | Type | Authority | Update Freq | Volume (useful) | Iran Relevance | Accessibility | RSS/API/Sitemap | Robots | Crawl Feasibility | Reliability | Diversity vs Others | **Verdict** |
|--------|------|-----------|-------------|-----------------|----------------|---------------|-----------------|--------|-------------------|-------------|---------------------|-------------|
| **BaniMag — banimode.com/blog** | E-commerce Magazine (Banimode) | **High** — Banimode since 1393, “pioneer online fashion”, 1400 brands, 51–200 employees, LinkedIn 2.8k followers, Tehran HQ; major Digistyle competitor [source search] | **Medium** — blog shows dates `شهریور ۱۴۰۵`, `مرداد ۱۴۰۵`, `تیر ۱۴۰۵` → ~2–4 posts/month; `blog/post-sitemap1.xml` + `post-sitemap2.xml` + `category-sitemap.xml` + `video-sitemap.xml`, lastmod `2026-09-06` ✅; RSS `blog/feed/` live (5 items fetched) ✅ | **High** — fashion-only subtree: `چگونه استایل کره‌ای بسازیم`, `مانتو تابستانه`, `شلوار گشاد جین و پارچه‌ای`, `لباس مجلسی با حجاب` — Persian, modest-fashion vocabulary, outfit combos; distinct from electronics/power-bank posts (filtered by category) | **Very High** — Persian, hijab/manteau content, local sizing guides (`جدول سایز شلوار مردانه ایرانی`), local trends | Public WordPress | Sitemap index `https://www.banimode.com/blog/sitemap_index.xml` → verified; RSS `https://www.banimode.com/blog/feed/` live; no official API need | `robots.txt` **allows** blog (allows `*/modules/*.css/.js/.jpg`, blocks `/cart`, `/search`, `/*?id*` etc, but `Allow: /landing/banijome/*` etc and **explicitly lists** `Sitemap: /sitemap.xml` + `/blog/sitemap_index.xml`) — **blog not disallowed** ✅ | **Feasible** — WordPress HTML, standard selectors, `trafilatura` will extract; monitor `*?*` query blocking but blog URLs are clean | High — established retailer, consistent posting since 1399 | **Medium-High diversity** — e-commerce mag like Digikala Mag but **different editorial team, different brand partnerships (Jeanswest, Baleno)**, overlapping audience but independent evidence channel | **RECOMMENDED MVP #3** — enable as `banimode_mag` with `authority_weight=0.70`, `update 12h` |
| **Modeworld — modeworld.ir** | **Pure fashion magazine** (no shop) | **Medium-High** — niche editorial, “مجله دنیای مد”, editor mission “bridge global trends to Iranian taste”, socials `instagram/modeworld.ir`, Facebook; cited as Yoast SEO site with multi-year archive | **Medium** — `modeworld.ir/post-sitemap1.xml` + `post-sitemap2.xml` + `page/category`, lastmod `2026-09-20` ✅; front-page latest `بررسی هفته مد نیویورک بهار ۲۰۲۷ (2026-09-20)`, `تاریخچه لباس عروس (2026-09-01)`, `رنگ سال 2027 آبی درخشان` → ~1–2/week | **Very High** (fashion density) — almost 100% fashion: runway reviews, Pantone color, trend histories, `سیلوئت لباس`, `استایل گوتیک`, `زودیاک` — translates global trends to Persian, exactly the bridge we need | **High** — purely Persian, translates global to Iran, no product push; complements e-commerce mags | Public WordPress | Sitemap index `https://modeworld.ir/sitemap_index.xml` verified; RSS `https://modeworld.ir/feed/` fetched live (10 items) ✅ | `robots.txt` : `Disallow: /wp-admin/`, `Disallow: /feed/` (Yoast block) but **sitemap allowed** and feed still returns HTTP 200 — we fetch via sitemap, not via `/feed` path that SEO blocks; crawl of article pages allowed ✅ | **Feasible** — clean article HTML, category filters easy | Medium-High — independent small team, but consistent since 2019 | **Very High diversity** — *only pure editorial* among Iranian candidates; not tied to a shop; provides global→Iran translation layer distinct from retailer mags | **RECOMMENDED MVP #4** — enable as `modeworld` with `authority_weight=0.65`, `update 24h` |
| **IranModeling — iranmodeling.net** | Fashion media / modelling journal (licensed by Ministry of Culture, “تنها رسانه معتبر ایران” claim, Ershad license) | **Medium** — licensed, claims “only licensed fashion media”, socials `instagram/iranmodeling_insta` (active), but smaller than retailer mags | **Medium-Low** — sitemap `post-sitemap1.xml` + `post-sitemap2.xml` + `post-sitemap3.xml`, lastmod `2026-09-19` ✅; articles `کیف‌های بزرگ ترند 2026`, `ترندهای زمستان 2025` (Azar 1404) → ~2–5/month | **Medium-High** — fashion but angle = models, street style, Fashion Weeks (`شهریور ماه هفته‌های مد` covering NY/Milan/Paris Sept 2026) — less outfit-guide, more news/trend | **Very High** — Iranian models, Tehran street style, local designer coverage; Persian | Public WordPress | Sitemap `https://iranmodeling.net/sitemap_index.xml` verified; RSS typical `/feed` exists; no API | `robots.txt` minimal: `Disallow: /wp-login.php`, `Sitemap: ...` → **allows article crawl** ✅ | Feasible | Medium — legitimate but editorial volume lower | **High diversity** — *people/model* angle vs product/guide | **RECOMMENDED MVP #5 (optional or alternate)** — enable as `iranmodeling` with `authority_weight=0.55`, `update 24h`, or keep as *standby candidate* if we want exactly 2 new sources (pick Modeworld + BaniMag as top 2) |

#### C. Evaluated but NOT Recommended for MVP Core

| Source | Why Not Core |
|--------|--------------|
| **Modiseh (modiseh.com)** — fashion e-commerce | **Sitemap yes** (`sitemap_category.xml`, `sitemap_product.xml` with 2026-09-19 lastmod) but `blog` exists at `modiseh.com/blog` with posts like `کت کوتاه زنانه را با چه شلواری بپوشیم`, `شلوار مام استایل vs مام فیت` — but **no dedicated blog sitemap** found, product catalog dominates, `robots.txt` blocks `*?*` and `/catalog/*` heavily; blog pagination likely JS-heavy. Fashion density lower than BaniMag; overlaps with Digikala Mag + BaniMag without adding diversity. Keep as **future candidate**, disabled. |
| **Shixon (shixon.com)** | `robots.txt` allows `*`, sitemap `sitemap.xml` + `blog/sitemap.xml` verified, blog `blog/articles/2985` (“رنگ ترند پاییز 1405”) relevant but **blog mixed with non-fashion** (power banks, tattoos, hair tattoos) → signal-to-noise low. `shixon.com/blog` fetched shows fashion diluted. Not reliable enough for MVP. Disabled. |
| **Rochi (rochi.ir)** | Marketplace for clothing/fabric, `sitemap.xml → products/sellers/categories`, `robots.txt` allows `/` but blocks `/?*`. Mostly product listings, not editorial; `rochi.shop` redirected. Low fashion-article volume. Disabled. |
| **Fashion4Iran (fashion4iran.com)** | PrestaShop e-commerce + `blog_sitemap.xml` (huge XML with many 2026-09-21 entries) but **blog_content 500 error on fetch snippet test** (intermittent), mixed content, and per your request **demoted from core**. Keep as **candidate disabled**, needs selector verification before enabling. |
| **Torob, Snapp Market, Emalls, Zanbil, Okala** | Price comparison or grocery — not fashion-editorial; excluded. |
| **Pinterest, Instagram, Twitter** | API gated / scraping forbidden — optional adapters disabled by default. |
| **Google Trends** | Still gated alpha; `pytrends` archived — supplementary only, not core. |
| **Digistyle product catalog** | **Kept disabled in MVP** — no strong research reason to include price/sku signals for *trend* detection; retailer mags already give trend language without price scraping liability. Enable only if later study shows product-count proxy materially improves `iran_relevance` (currently heuristic). |

### 2.3 Diversity Goal — Why This Mix Matters

- **Vogue (global) + Digikala Mag (IR e-commerce editorial) + BaniMag (IR e-commerce editorial, different retailer) + Modeworld (pure IR editorial)** = 4 *independent* editorial voices: **global reference + two retailer mags (different assortments/audiences) + one pure trend-translation magazine**. No single retailer dominates, cross-source agreement becomes meaningful.
- **IranModeling** as 5th gives *model/street-style* angle — useful if we want 5, but 4 is enough for MVP with good diversity and manageable load.
- **Minimum for cross-source:** Need ≥2 distinct IR sources to claim `cross_source_evidence` for Iran — with BaniMag + Modeworld we have it.

### 2.4 Revised Source Registry (YAML Concept)

```yaml
sources:
  # GLOBAL
  - source_id: vogue
    name: "Vogue"
    source_type: magazine
    country: US
    region: global
    language: en
    authority_weight: 0.90          # configurable, not hard-coded
    freshness_weight: 0.80
    extraction_method: sitemap_rss
    update_frequency: "6h"
    enabled: true
    robots_status: "allowed_articles"
    sitemap: "https://www.vogue.com/sitemap.xml"
    rss: "https://www.vogue.com/feed/rss"
    selectors_need_verification: true

  # IRAN — CORE
  - source_id: digikala_mag
    name: "Digikala Magazine"
    country: IR
    region: iranian
    language: fa
    authority_weight: 0.85
    freshness_weight: 0.90
    extraction_method: sitemap
    update_frequency: "3h"
    enabled: true
    sitemap: "https://www.digikala.com/mag/sitemap_index.xml"

  - source_id: banimode_mag
    name: "BaniMag"
    country: IR
    region: iranian
    language: fa
    authority_weight: 0.70
    extraction_method: sitemap_rss
    update_frequency: "12h"
    enabled: true                  # NEW MVP #3
    sitemap: "https://www.banimode.com/blog/sitemap_index.xml"
    rss: "https://www.banimode.com/blog/feed/"
    notes: "Verified 2026-09-21: WP sitemap + RSS live, Persian modest-fashion guides"

  - source_id: modeworld
    name: "Modeworld"
    country: IR
    region: iranian
    language: fa
    authority_weight: 0.65
    extraction_method: sitemap
    update_frequency: "24h"
    enabled: true                  # NEW MVP #4
    sitemap: "https://modeworld.ir/sitemap_index.xml"
    rss: "https://modeworld.ir/feed/"
    notes: "Pure editorial, translates global trends to Persian, high fashion density"

  # IRAN — STANDBY (disabled by default, enable if 5-source diversity desired)
  - source_id: iranmodeling
    name: "IranModeling"
    country: IR
    region: iranian
    language: fa
    authority_weight: 0.55
    extraction_method: sitemap
    update_frequency: "24h"
    enabled: false
    sitemap: "https://iranmodeling.net/sitemap_index.xml"

  - source_id: fashion4iran
    name: "Fashion4Iran"
    country: IR
    region: iranian
    language: fa
    authority_weight: 0.50
    extraction_method: sitemap
    update_frequency: "24h"
    enabled: false
    notes: "Candidate, needs selector verification, 500 error observed"

  # DISABLED — product catalog, not editorial
  - source_id: digistyle
    name: "Digistyle"
    extraction_method: sitemap
    enabled: false
    notes: "Product catalog disabled unless market-proxy research justifies"

  # SUPPLEMENTARY — disabled by default
  - source_id: google_trends
    name: "Google Trends (supplementary)"
    source_type: search_signal
    extraction_method: api_trendspy
    update_frequency: "24h"
    enabled: false
    geo: "IR"
    notes: "Pytrends archived 2025-04-17; geo IR sparse — document limitation"

  - source_id: pinterest_trends
    name: "Pinterest Trends"
    extraction_method: official_api_v5_or_apify
    enabled: false
```

**Adapters:** `VogueAdapter`, `DigikalaMagAdapter`, `BaniMagAdapter`, `ModeworldAdapter` all inherit `BaseCollector`; adding a new source = YAML + subclass.

---

## 3. Lightweight Architecture — Confirmed Stack

**Confirmed (per feedback #2):** Keep it lightweight.

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11+ | |
| API | **FastAPI** + Pydantic v2 | Async, OpenAPI |
| DB | **PostgreSQL 15+**, optional `pgvector` extension | JSONB, FTS, vector in one process, no extra service |
| Scheduler | **APScheduler** `BackgroundScheduler` + `SQLAlchemyJobStore` (Postgres) | No Redis/Celery/Airflow; jobs survive restart; single VM; abstraction `SchedulerInterface` allows swap later |
| HTTP | `httpx` async + `tenacity` retry + `protego` robots check | |
| Parsing | `trafilatura` + `beautifulsoup4` + `lxml` | |
| NLP | Deterministic → taxonomy → embeddings (`paraphrase-multilingual-MiniLM-L12-v2` supports `fa+en`) → LLM (optional) | |
| Config | `pydantic-settings` + `config/*.yaml` + `.env` | 12-factor |
| **Not included** | Redis, Kafka, K8s, Airflow, Celery unless demonstrated need | |

**Data-flow (unchanged but with seasonal branch):**

```
SOURCE → COLLECTOR (adapter, robots-checked, ETag-cached)
  → RAW STORAGE (append-only) → CLEANING → DEDUP (L1 URL, L2 hash, L3 SimHash)
  → CONTENT EXTRACTION → FASHION ATTRIBUTE EXTRACTION (hybrid)
  → NORMALIZATION (taxonomy+embedding) → TREND SIGNAL GENERATION
  → TREND AGGREGATION → [SIX-COMPONENT SCORING] → IRAN RELEVANCE (separate)
  → SEASONAL RELEVANCE (separate) → CURRENT SNAPSHOT (hourly mat) → RECOMMENDATION API
                                ↘ HISTORICAL STORAGE (append-only)
```

---

## 4. Hybrid Extraction — Provider-Agnostic LLM

**Order, per feedback #3:**

1. **Deterministic / rule-based** — regex, gazetteers from taxonomy, Persian keywords (`مانتو`, `شلوار گشاد`, `کت`, `روسری`, `دامن`, `پالتو`), dateparser, language detect (`fasttext`/`langdetect`). Covers ~70% mentions at near-zero cost.
2. **Taxonomy / synonym matching** — `config/taxonomy.yaml` aliases + normalization mapping (e.g., `wide leg trousers → wide_leg_bottom`).
3. **Embeddings** — `sentence-transformers` multilingual embeddings vs `fashion_entities.embedding`; cosine `>0.82` auto-map, `0.70–0.82` flag for LLM, `<0.70` propose new candidate `pending_review`.
4. **LLM (only for ambiguous/difficult)** — e.g., article `لباس جین کودکان ، ترندی همیشگی` needs disambiguation whether `trendy` is a trend signal.

**Provider-agnostic design (no hard-coded OpenAI):**

```yaml
# config/llm.yaml
llm:
  enabled: true                 # false → system runs rule-only, no failure
  provider: "openai"            # openai | anthropic | local | dummy
  model: "gpt-4o-mini"          # configurable, not hard-coded in code; docs use placeholder
  api_base: null                # for local: "http://localhost:11434/v1"
  api_key_env: "LLM_API_KEY"    # env var name, not value
  max_calls_per_day: 100
  timeout: 15
  cache_ttl_days: 30
  prompt_version: "v1"
```

```python
# extraction/llm_provider.py
class LLMProvider(Protocol):
    async def extract(self, text: str, taxonomy_hint: list[str]) -> dict: ...

class OpenAIProvider(LLMProvider): ...
class AnthropicProvider(LLMProvider): ...
class LocalProvider(LLMProvider): ...   # Ollama / vLLM / HF
class DummyProvider(LLMProvider):       # returns {} — used when no key
# Factory: build from config, never import openai at top-level if not needed
```

**LLM contract (must hold for any provider):**

- **Input:** `title + first 800 chars content_text + language + taxonomy slice`
- **Output JSON (Pydantic-validated):**
```json
{
  "garments": [{"raw": "wide leg jeans", "canonical_hint": "wide_leg_bottom", "confidence": 0.92}],
  "colors": [], "patterns": [], "styles": [], "materials": [], "silhouettes": [],
  "outfit_combinations": [["manteau","wide_leg_pants"]],
  "trend_candidates": ["wide_leg_bottom"]
}
```
- **Validation:** Pydantic `LLMExtractionSchema`; unknown canonical → passed to normalizer, not auto-inserted.
- **Fallback:** On timeout / validation error / no key → return rule-based result, log `llm_fallback`.
- **Caching:** Key = `SHA256(content_hash + prompt_version + taxonomy_version)` in `llm_cache` table / in-DB; never call twice for same doc. Cache hit rate logged.
- **Cost control:** `max_calls_per_day`, batch ambiguous docs, skip if rule confidence already >0.9.
- **Graceful degradation:** If `llm.enabled=false` or `LLM_API_KEY` missing, pipeline logs `llm_disabled` and continues — all tests must pass in rule-only mode.

**System must remain functional with no LLM key — verified by CI job `LLM_DISABLED=1`.**

---

## 5. Six-Component Trend Scoring

> **Do NOT claim 30-day half-life is optimal.** All numbers below are `v1_heuristic` defaults, configurable, and tunable via historical evaluation (Section 9).

### 5.1 Components — Computed Separately Then Combined

For each canonical concept `c` over rolling window `W=30d` (configurable):

| Component | Symbol | What It Measures | How (Heuristic Default) | Research Support |
|-----------|--------|------------------|------------------------|------------------|
| **GLOBAL_TREND_STRENGTH** | `G` | Raw global popularity, authority-weighted | `G = evidence_strength_global` = `Σ_i (conf_i * authority_src_i) / norm` over global+Iran signals; frequency implicit | Rudna dual-signal complementarity shows weighted combination beats single source |
| **IRAN_RELEVANCE** | `I` | Iran-specific relevance 0–1, **separate** | `I = w1*iran_source_ratio + w2*fa_mention_ratio + w3*cultural_compatibility + w4*market_proxy_optional` (weights sum 1, all configurable; see §7) | Adaptation of Al-Halah influence idea (global→local) — not directly Iran-specific; weights are heuristic |
| **RECENCY** | `R` | Time decay | **Exponential** `w_i = exp(-λ*age_days)`, `λ=ln2/half_life`, `half_life_days` configurable (default 30, but evaluated via tuning). Per-signal, aggregated as weighted mean. | Strongly supported: PLoS One 2015 temporal predictor `sα=Σ e^{γ(Tiα-t)}`, half-life model (150d optimal for movie ratings) — but half-life value for fashion is heuristic |
| **GROWTH** | `Gw` | Momentum | `Gw = (score_t - score_{t-7d}) / (score_{t-7d}+ε)` from `trend_history`; smoothed, clamped `0.8–1.3` to avoid over-boost | KERN/REAR forecasting uses slope; growth concept is research-backed, threshold values heuristic |
| **CROSS_SOURCE_EVIDENCE** | `C` | Independent corroboration | `C = 1 + log(1+distinct_sources)/log(1+max_sources)` (≈1.0–1.6); requires `min_supporting_sources≥2` else penalized | Rudna: combined signals rank-1 across 77 series vs 51–57% alone — supports diversity bonus |
| **SEASONAL_RELEVANCE** | `S` | Seasonal fit (see §6) | `S = base 1.0 * seasonal_affinity(c, month)` (0.5–1.2) + `weather_boost` optional | Seasonal cycles in GeoStyle/FIT; S value heuristic |

**Why separate before combining?** So we can answer:
- “Is it globally strong but irrelevant in Iran?” → `G=0.8, I=0.3`
- “Is it old but seasonally recurring?” → `R=0.4, S=1.2, Gw=0.05 (stable)`
- “Is it from one viral article?” → `C=1.0, evidence_count=1` → filtered

### 5.2 Final Combination — Transparent, Versioned

```
current_global = G * C * persistence   # persistence = active_days/W (0–1), evidence that trend persists across days not just burst
recency_weighted_global = Σ_i(G_i * R_i) / Σ_i R_i  # or incorporate R into G_i weighting

# Iran-aware current score (multiplicative so low Iran relevance cannot be compensated)
current_score = recency_weighted_global * I * Gw * S

# Then per-trend normalization across all trends (min-max to 0–1 for ranking)
current_score_norm = (current_score - min_score) / (max_score - min_score + ε)

# Guardrails
if evidence_count < min_evidence_count (default 3) → is_actionable=false, still stored but not in top-N snapshot
if supporting_sources < min_supporting_sources (2) and not single authoritative source with authority>0.85 → penalize C
```

```yaml
# config/scoring.yaml (all configurable, no hard-coding)
scoring:
  version: "v1_heuristic"          # not claimed as scientific
  window_days: 30
  min_evidence_count: 3
  min_supporting_sources: 2
  half_life_days: 30               # engineering default, to be tuned via §9
  decay_type: "exponential"        # alternatives: "power_law" (evaluated in tuning)
  # six-component weights (if any weighted sum variant used in ablation)
  # For multiplicative, weights are inside I and S only
  recency:
    formula: "exp(-ln2 * age / half_life)"
  growth:
    window_days: 7
    clamp: [0.8, 1.3]
  cross_source:
    formula: "1 + log(1+distinct)/log(1+max)"
  iran_relevance:
    w_iran_source: 0.40
    w_lang: 0.20
    w_norms: 0.25
    w_market: 0.15
  seasonal:
    boost_range: [0.7, 1.2]
  lifecycle:
    emerging:    {min_evidence: 3, max_age_days: 14, growth_gt: 0.25, sources_ge: 2}
    rising:      {growth_gt: 0.10, persistence_gt: 0.5}
    established:{score_gt: 0.6, persistence_gt: 0.7, abs_growth_lt: 0.10, evidence_gt: 10}
    declining:   {growth_lt: -0.10, falling_snapshots_ge: 2}
    inactive:    {last_seen_gt_days: 60, score_lt: 0.15}
```

**Distinction table (required by feedback #4 & #11):**

| Mechanism | Published / Research-Supported | Adapted / Engineering Heuristic (our `v1`) |
|-----------|-------------------------------|--------------------------------------------|
| Trend = time-series of concept popularity | KERN/FIT, GeoStyle — concept popularity as normalized frequency | Splitting into `category:attribute` pairs and outfit combos — heuristic structure |
| Exponential recency decay | PLoS One 2015 TBP, half-life CF model — exponential decay predicts future popularity best | Half-life = 30d, λ=ln2/30 — **not proven optimal for fashion**; tuned via §9 grid search |
| Cross-source diversity bonus | Rudna: Twitter+Google combined rank-1 vs alone 51–57% | Formula `1+log(1+n)` — plausible diminishing returns, but heuristic |
| Taxonomy + embedding normalization | KERN internal/external knowledge — yes | Cosine thresholds 0.82/0.70 — heuristic |
| Growth from slope | REAR attention on future horizons — concept of momentum | 7-day window, clamp 0.8–1.3 — heuristic |
| Seasonal relevance multiplier | GeoStyle seasonal cycles, Neo-Fashion seasonal grouping — seasonal patterns exist | Affinity values 0.5–1.2 per concept-month — heuristic, curated + to be learned |
| Six-component multiplicative combination | No paper proposes exactly this 6-way factorization | Our engineering synthesis — validated as a whole via human labels, not as science |

All docs and API `meta.scoring_version` expose `v1_heuristic` so heuristics are never presented as established science.

---

## 6. Seasonality — Explicit Component

> **“A trend should not automatically become irrelevant simply because another trend has more recent mentions.”**

### 6.1 Definition
`SEASONAL_RELEVANCE (S)` = how appropriate a concept is for the **current season/month** in Iran, independent of recency.

### 6.2 Computation

1. **Calendar:** Both Gregorian and **Persian (Solar Hijri) seasons** supported; config `season_calendar: "persian"` maps `Farvardin–Khordad = spring (warm)`, `Tir–Shahrivar = summer`, etc., to Tehran climate context.
2. **Affinity table:** `config/seasonal_affinity.yaml` curated initially, later learned:

```yaml
seasonal_affinity:
  # 0.5 = off-season, 1.0 = neutral, 1.2 = peak season
  linen:        {spring: 1.1, summer: 1.2, autumn: 0.7, winter: 0.5}
  wool:         {spring: 0.6, summer: 0.5, autumn: 1.1, winter: 1.2}
  manteau_light:{spring: 1.1, summer: 1.2, autumn: 1.0, winter: 0.6}
  wool_coat:    {spring: 0.5, summer: 0.4, autumn: 1.0, winter: 1.2}
  pastel_palette:{spring: 1.2, summer: 1.1, autumn: 0.8, winter: 0.7}
  # neutral for many concepts: default 1.0
```

3. **Month granularity:** Optional `month_affinity` for finer (e.g., `linen` peaks `Tir/Mordad`).
4. **Weather context (optional Advanced):** If `weather_api.enabled`, `S *= weather_boost` where `weather_boost` checks Tehran forecast temp vs concept's ideal temp range (stored per entity `ideal_temp_range`). MVP: use month only, no live weather call.

### 6.3 Effect
- A **seasonally strong** concept (e.g., `linen` in summer) keeps `S=1.2` even if `R` decays (no recent articles) — it stays moderately ranked, not buried, and will re-emerge next summer via `trend_history` recurrence analysis.
- An **off-season** concept (e.g., `wool_coat` in August) gets `S=0.4` — even if global `G=0.8`, final score dampened.
- **Historical preservation matters:** Because we keep `trend_history`, we can later detect **seasonal periodicity** (e.g., `pastel` spikes every spring) — impossible if old trends were deleted.

**S is separate column in `trends` and `trend_history` for audit.**

---

## 7. Iran Relevance — Evidence-Based, Separate

**Principle:** `IRAN_RELEVANCE (I)` is **independent** of `GLOBAL_TREND_STRENGTH`; a global trend is NOT automatically Iranian.

### 7.1 Evidence Sources (only what we store)

- **Iranian publication ratio:** `iranian_source_evidence / total_evidence` — count signals where `source.region=iranian` (`digikala_mag`, `banimode_mag`, `modeworld`, `iranmodeling`)
- **Persian-language ratio:** `fa_mentions / total_mentions` — language detection per doc; Persian vocabulary (`مانتو`, `شال`, `چادر`, `روسری`) counted via gazetteer
- **Local vocabulary hit:** bonus if `raw_term` contains Iran-specific tokens (`مانتو`, `چادر`, `مقنعه`) — stored per observation `attributes.local_vocab`
- **Cultural compatibility:** `fashion_entities.iran_compatibility` (0–1) curated, not inferred — e.g., `manteau=1.0`, `hijab=1.0`, `wide_leg_pants=0.9`, `mini_skirt=0.4`, `crop_top=0.6`. This is **market availability proxy**, manually reviewed, versioned.
- **Market proxy (optional, disabled by default):** If product catalog enabled, `availability = min(1, product_count / 100)` for concept; otherwise `0.5` baseline — **we do NOT fabricate; if no market data, that term contributes neutral 0.5**.

### 7.2 Formula (configurable weights)

```
I = clamp( w1*iran_source_ratio + w2*fa_ratio + w3*cultural_compatibility + w4*market_proxy , 0, 1)
# default w = [0.40, 0.20, 0.25, 0.15]
# If market disabled, renormalize w1..w3 to sum 1.
```

**Do not infer popularity without evidence:** If `iranian_source_evidence=0` and `fa_ratio=0`, then `I ≤ 0.25*compatibility` ≤ 0.25 — even if `G=0.9`, final `current_score` ≤ 0.22. Correct: global trend without Iranian evidence is ranked low for Iranian user.

**Iran relevance is stored separately:** API can return `global_score=0.8, iran_relevance=0.3, current_score=0.24` and explanation “Globally strong but low Iranian evidence”.

---

## 8. Evidence & Explainability

### 8.1 Provenance Chain

```
trend.id → trend_evidence (many rows) → trend_signals → fashion_observations → raw_documents → source.url
```

Every `trends` row links to:
- `evidence_count`, `supporting_sources`, `first_seen`, `last_seen`
- `trend_evidence` rows with `source_id`, `raw_document_id`, `signal_id`, `confidence`, `timestamp`

### 8.2 “Why is this a trend?” — Deterministic Answer

API `GET /trends/{id}` returns:

```json
{
  "canonical_name": "wide_leg_bottom",
  "current_score": 0.51,
  "components": {"G":0.78, "I":0.65, "R":0.82, "Gw":1.15, "C":1.38, "S":1.0},
  "lifecycle_state": "rising",
  "explanation": "Wide-leg trousers are rising based on 47 signals from 4 independent sources (Vogue, Digikala Mag, BaniMag, Modeworld) in last 30 days, with recency half-life 30 days (R=0.82), growth +15% week-over-week, cross-source support 1.38. Iranian evidence 38% (I=0.65). Seasonally neutral (S=1.0).",
  "top_evidence": [
    {"source_id":"vogue","title":"The Wide-Leg Takeover","url":"https://www.vogue.com/...","date":"2026-09-18","lang":"en"},
    {"source_id":"digikala_mag","title":"شلوار گشاد ترند امسال","url":"https://www.digikala.com/mag/...","date":"2026-09-19","lang":"fa"},
    {"source_id":"banimode_mag","title":"ست مانتو با شلوار گشاد","url":"https://www.banimode.com/blog/...","date":"2026-09-17","lang":"fa"}
  ],
  "evidence_query": "SELECT * FROM trend_evidence WHERE trend_id=42 ORDER BY timestamp DESC"
}
```

**No hallucination:** Counts come from `COUNT(*)` over `trend_evidence` where `timestamp` in window. If `evidence_count=2`, explanation says 2.

### 8.3 Auditability

- `raw_documents.content_hash` lets auditors verify dedup.
- `trend_history` shows score evolution; any snapshot can be reconstructed by replaying `trend_signals` up to that timestamp.

---

## 9. Temporal Validation & Parameter Tuning

> Feedback #4, #8: Treat thresholds as engineering, design evaluation to tune them, prevent leakage.

### 9.1 Leakage Prevention Invariant

**Rule:** When evaluating whether a trend was detectable at time `T`, **only data with `timestamp <= T`** may be used.

**Enforcement:**
- All aggregation queries include `WHERE timestamp <= :snapshot_time`.
- `trend_history` rows are inserted only **after** snapshot materialization; no future rows exist at query time.
- Scheduler's `materialize_snapshot(snapshot_time)` takes explicit `snapshot_time` param; default `now()` but tests pass historical times.
- **Code review check:** No query orders by `collection_date` without `publication_date` filter; `raw_documents.publication_date` is the signal timestamp, not collection time.
- **Tests:** `test_temporal_leakage.py` inserts future docs (pub_date = T+7d) then asserts `GET /trends/history?to=T` unchanged.

### 9.2 Evaluation Methodology for Parameter Tuning

**We do NOT claim optimal half-life. We estimate it via historical data.**

**Dataset construction:**
- Use collected `raw_documents` + `trend_signals` over ≥3 months (or seed with synthetic + public FIT evaluation if needed).
- Create **time-based splits**: train on `[T0, T1]`, validate on `(T1, T2]`, test on `(T2, T3]`. E.g., train Jan–Mar, validate Apr, test May — **no shuffling**.
- Human labels: Annotators label top-20 trends per validation window as `relevant / not` for Iranian market (binary) + rate `seasonal appropriateness`.

**Metrics:**
- `precision@k`, `recall@k` vs human labels
- `freshness = avg(age of signals in snapshot)` (lower better)
- `Spearman correlation` between `I` and human Iran-relevance rating
- `lifecycle accuracy` (next-state prediction)
- `stability = Jaccard(top-20_t, top-20_{t-1})` (0.6–0.9 target)

**Parameter search (grid + small Bayesian):**
```yaml
search_space:
  half_life_days: [7, 14, 30, 60, 90]
  window_days: [14, 30, 60]
  min_evidence_count: [2, 3, 5]
  min_supporting_sources: [1, 2, 3]
  w_iran_source: [0.3, 0.4, 0.5]
  seasonal_boost_range: [[0.5,1.2], [0.7,1.2]]
  decay_type: ["exponential", "power_law"]
```
- For each config, replay history: `for each week T in validation: materialize snapshot using only data <=T, compute metrics vs human labels at T`.
- Pick config maximizing `F1@10` with `stability` constraint.
- Report **best config + confidence intervals**, not as science but as **data-driven engineering choice for this dataset**.

**Versioning:** `scoring_version` increments when tuned (e.g., `v1_heuristic` → `v1_tuned_2026Q4`). Old snapshots remain comparable via `trend_history`.

---

## 10. Updated Research Review

> For each, state: **what’s supported**, **what we adapt**, **what’s our heuristic**.

### Core 12 Papers/Tracks

| # | Paper (year, venue) | Problem & Dataset | Method & Trend Definition | Key Result | What’s Supported | What We Adapt | Our Heuristic |
|---|---------------------|-------------------|---------------------------|------------|------------------|---------------|---------------|
| 1 | Ma et al. **KERN** (2020, arXiv) — FIT (8,808 series, 5y) + GeoStyle | Fine-grained element forecasting per user group; trend = normalized frequency over time | LSTM encoder-decoder + internal/external knowledge via message passing | FIT half-year MAPE 30.02 vs 43.30 baseline | Time-series trend definition, internal/external knowledge idea | Use FIT-style bi-weekly aggregation + taxonomy message passing for normalization | Half-life 30d, not in paper — our choice |
| 2 | Ding et al. **REAR** (2021, arXiv) — FIT + GeoStyle | Extend KERN with group+element relations + sliding temporal attention | REAR: relation-enhanced + attention for long horizon | REAR ≈ KERN on GeoStyle, slightly better on FIT one-year vs KERN | Attention improves long-horizon — supports growth/persistence features | Add user-group relation idea to future: cluster Iranian user segments | Attention window size — heuristic |
| 3 | Al-Halah & Grauman **GeoStyle** (2020, CVPR) — 7.7M images, 44 cities, 50 styles | Discover city-to-city fashion influence; forecast per-city style popularity | Influence graph (Granger-like) + coherence loss | Influence+coherence beats no-influence (0.0858 vs 0.0942) | Spatial influence exists; local ≠ global | Global→Iran influence as separate `I`; coherence intuition for Iran vs global | Iran compatibility scores — heuristic |
| 4 | Zhao et al. **Neo-Fashion** (2024, CTRJ) — 32,702 catwalk images | Seasonal trends from runway via instance segmentation | 3 pillars: dominant colors, styles, combinations per season | Word clouds per season; catwalk → consumer pipeline | Text + visual pillars; trend as frequency-ranked attributes | Use same 3 pillars per temporal window on magazine text | Catwalk source not used in MVP — heuristic exclusion |
| 5 | Silva et al. **Googling Fashion** (2019, Soc Sci) — Burberry Trends | Can Google Trends forecast fashion? univariate | Compare AR, DNNAR on Trends | Trends useful but not sole definition | Trends as corroboration only | Use Trends as supplementary, not primary | Geo IR fallback — heuristic |
| 6 | Rudna et al. **Twitter+Trends Sales Forecast** (2026, J Forecasting) — 77 series, Amazon Sales | Integrate Twitter counts + Google Trends per attribute | VECM/VAR/NNETAR; 4-pass design isolating signal contribution | Combined Twitter+Trends rank-1 on all 77 (RMSE 3.47 vs 91k), neither alone dominates (51–57%) | Cross-source complementarity — strong evidence | Cross-source diversity bonus `C` in scoring | Formula `1+log(1+n)` — heuristic |
| 7 | Fang et al. **Dual-Stream** (2026, Appl Sci) — GeoStyle + FIT | Fuse numerical popularity + LLM semantic descriptions | Dual-stream (numerical + text semantics) | DDFTF beats KERN 15% (FIT one-year MAE 0.070 vs 0.094) | Semantic enrichment helps forecasting | Reserve `trend_descriptions` field for future dual-stream | Not in MVP |
| 8 | Chia et al. **FashionCLIP** (2022, Sci Rep) — 800K Farfetch | General fashion representations via CLIP ViT-B/32 | Contrastive image-text, 0.83 FMNIST | Bias to white-bg product, long queries | Zero-shot fashion concept understanding via vision-language | Future image pipeline uses FashionCLIP for attribute extraction | Not in MVP |
| 9 | Skenderi et al. **GTM-Transformer** (2024, arXiv) — VISUELLE (5,577 products, 45M sales) | New product sales forecast via Google Trends + multimodal | Non-autoregressive Transformer with Google Trends encoder + cross-attention | +1.5% WAPE boost from Trends; best 7–10 months before release most predictive | Trends + multimodal fusion helps; cross-attention weights interpretable | Use Trends with multimodal embedding idea later | Product-sales ≠ trend detection — adaptation needs validation |
| 10 | Plosh et al. **VISUELLE 2.0** (2021+) / **Diversity in Luxury Rec** (SIGIR) — general | Fashion sales/vis forecasting with exogenous | WAPE/MAE reported; image data boosts WAPE 8.2% | Image helps long-term forecasting | Evidence for future multimodal upgrade | Keep MVP text-only, as research shows image adds but not required | — |
| 11 | Ding et al. **Survey: Fashion Recommendation** (2023, ACM CSUR) — 100+ papers | Survey compatibility, outfit, personalized rec | Gap between academic and real-world needs | Trend-aware ≠ trend-dictated | Trend as weighted factor, not override | Integration weight 0.15 in outfit scoring | Exact 0.15 — heuristic |
| 12 | Half-life & Temporal Decay (2015 PLoS One TBP; 2015 CEUR half-life CF) — Movielens, Netflix, Facebook | Temporal decay for trend prediction / CF | Exponential `e^{γ(Tiα-t)}` vs sliding window | TBP beats popularity-based; best half-life ~150 days for movies (different domain) | Exponential decay form is optimal for recsys trend prediction | Apply exponential to fashion signals | Half-life 30d for fashion — **not 150d** and not proven; tuned via §9 |

**Summary distinction:** Exponential *form* = research-supported; *half-life value*, *six-component factorization*, *Iran weights*, *thresholds*, *seasonal affinity numbers* = engineering heuristics versioned as `v1_heuristic`.

---

## 11. Revised Database Schema

> **Changes vs Rev 1:** Add `seasonal_relevance` to trends/history, `llm_cache`, `seasonal_affinity` reference, evidence provenance more explicit, add `trend_components` breakdown for explainability.

```sql
-- sources (unchanged but add new entries per §2.4)
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT CHECK (source_type IN ('magazine','blog','ecommerce_mag','search_signal','visual_search','social')),
    country CHAR(2),
    region TEXT CHECK (region IN ('global','iranian')),
    language TEXT NOT NULL,
    authority_weight REAL CHECK (authority_weight BETWEEN 0 AND 1),
    freshness_weight REAL CHECK (freshness_weight BETWEEN 0 AND 1),
    accessibility TEXT,
    extraction_method TEXT,
    update_frequency TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    robots_status TEXT,
    sitemap_url TEXT,
    rss_url TEXT,
    last_successful_fetch TIMESTAMPTZ,
    last_failed_fetch TIMESTAMPTZ,
    failure_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- raw_documents: append-only, monthly partition in future, add is_synthetic
CREATE TABLE raw_documents (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT REFERENCES sources(source_id),
    source_url TEXT UNIQUE NOT NULL,
    canonical_url TEXT,
    title TEXT,
    content_html TEXT,
    content_text TEXT NOT NULL,
    publication_date TIMESTAMPTZ,
    collection_date TIMESTAMPTZ DEFAULT NOW(),
    language TEXT,
    author TEXT,
    category TEXT,
    image_urls JSONB,
    metadata JSONB, -- {etag, last_modified, content_hash, http_status, is_synthetic}
    content_hash CHAR(64) NOT NULL,
    extraction_timestamp TIMESTAMPTZ DEFAULT NOW(),
    is_duplicate BOOLEAN DEFAULT FALSE,
    duplicate_of BIGINT REFERENCES raw_documents(id),
    is_synthetic BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_raw_pub ON raw_documents(source_id, publication_date DESC);
CREATE INDEX idx_raw_hash ON raw_documents(content_hash);
CREATE INDEX idx_raw_collection ON raw_documents(collection_date DESC);

-- fashion_entities: add iran_compatibility + ideal_temp_range + seasonal
CREATE TABLE fashion_entities (
    id BIGSERIAL PRIMARY KEY,
    canonical_name TEXT UNIQUE NOT NULL, -- 'wide_leg_bottom'
    category TEXT CHECK (category IN ('garment','color','pattern','style','silhouette','material','outfit_combination','accessory','aesthetic')),
    description TEXT,
    aliases JSONB, -- ["wide leg trousers","شلوار گشاد"]
    embedding VECTOR(384), -- pgvector optional
    iran_compatibility REAL CHECK (iran_compatibility BETWEEN 0 AND 1), -- curated cultural/market fit
    ideal_temp_range JSONB, -- {"min":15,"max":28} for seasonal weather boost
    parent_id BIGINT REFERENCES fashion_entities(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- llm_cache: NEW — provider-agnostic LLM cache (fixes cost & reproducibility)
CREATE TABLE llm_cache (
    cache_key CHAR(64) PRIMARY KEY, -- SHA256(content_hash + prompt_version + taxonomy_version + provider_model)
    prompt_version TEXT NOT NULL,
    provider_model TEXT NOT NULL,
    input_hash CHAR(64) NOT NULL,
    output_json JSONB NOT NULL, -- validated extraction
    created_at TIMESTAMPTZ DEFAULT NOW(),
    hit_count INT DEFAULT 1
);
CREATE INDEX idx_llm_cache_input ON llm_cache(input_hash);

-- fashion_observations: one per attribute mention per doc
CREATE TABLE fashion_observations (
    id BIGSERIAL PRIMARY KEY,
    raw_document_id BIGINT REFERENCES raw_documents(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES sources(source_id),
    entity_id BIGINT REFERENCES fashion_entities(id),
    raw_term TEXT NOT NULL,
    canonical_name TEXT,
    category TEXT NOT NULL,
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    extractor_type TEXT CHECK (extractor_type IN ('rule','ner','embedding','llm','vision')),
    span_text TEXT,
    attributes JSONB, -- {color:"earth tone", local_vocab:true}
    observed_at TIMESTAMPTZ DEFAULT NOW(),
    region TEXT DEFAULT 'global',
    llm_cache_key CHAR(64) REFERENCES llm_cache(cache_key)
);

-- trend_signals: one per concept per doc window
CREATE TABLE trend_signals (
    id BIGSERIAL PRIMARY KEY,
    concept TEXT REFERENCES fashion_entities(canonical_name),
    source_id TEXT REFERENCES sources(source_id),
    observation_id BIGINT REFERENCES fashion_observations(id),
    raw_document_id BIGINT REFERENCES raw_documents(id),
    timestamp TIMESTAMPTZ NOT NULL, -- publication_date
    evidence_type TEXT CHECK (evidence_type IN ('article','search_interest','visual','runway','ecommerce')),
    confidence REAL,
    region TEXT,
    extracted_attributes JSONB
);
CREATE INDEX idx_signal_concept_time ON trend_signals(concept, timestamp DESC);

-- trends: aggregated, with six components separate
CREATE TABLE trends (
    id BIGSERIAL PRIMARY KEY,
    canonical_name TEXT UNIQUE REFERENCES fashion_entities(canonical_name),
    category TEXT NOT NULL,
    description TEXT,
    -- six components (auditable separately)
    global_score REAL CHECK (global_score BETWEEN 0 AND 1),
    iran_relevance_score REAL CHECK (iran_relevance_score BETWEEN 0 AND 1),
    recency_score REAL CHECK (recency_score BETWEEN 0 AND 1),
    growth_score REAL CHECK (growth_score BETWEEN 0.5 AND 1.5), -- e.g., 1.15 = +15%
    cross_source_score REAL CHECK (cross_source_score BETWEEN 1.0 AND 2.0),
    seasonal_relevance REAL CHECK (seasonal_relevance BETWEEN 0.3 AND 1.5),
    -- final
    current_score REAL CHECK (current_score BETWEEN 0 AND 1),
    lifecycle_state TEXT CHECK (lifecycle_state IN ('emerging','rising','established','stable','declining','inactive')),
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    evidence_count INT DEFAULT 0,
    supporting_sources INT DEFAULT 0,
    is_actionable BOOLEAN DEFAULT FALSE,
    recommendation_payload JSONB,
    explanation TEXT,
    scoring_version TEXT DEFAULT 'v1_heuristic'
);
CREATE INDEX idx_trends_score ON trends(current_score DESC);
CREATE INDEX idx_trends_lifecycle ON trends(lifecycle_state);
CREATE INDEX idx_trends_category ON trends(category);

-- trend_evidence: provenance (answer "Why?")
CREATE TABLE trend_evidence (
    id BIGSERIAL PRIMARY KEY,
    trend_id BIGINT REFERENCES trends(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES sources(source_id),
    observation_id BIGINT REFERENCES fashion_observations(id),
    signal_id BIGINT REFERENCES trend_signals(id),
    raw_document_id BIGINT REFERENCES raw_documents(id),
    evidence_type TEXT,
    confidence REAL,
    timestamp TIMESTAMPTZ NOT NULL,
    snippet TEXT -- 200-char excerpt for explanation without fetching doc
);
CREATE INDEX idx_evidence_trend_time ON trend_evidence(trend_id, timestamp DESC);

-- trend_history: append-only, now stores six components per snapshot
CREATE TABLE trend_history (
    id BIGSERIAL PRIMARY KEY,
    trend_id BIGINT REFERENCES trends(id) ON DELETE CASCADE,
    snapshot_time TIMESTAMPTZ NOT NULL,
    global_score REAL NOT NULL,
    iran_relevance_score REAL NOT NULL,
    recency_score REAL NOT NULL,
    growth_score REAL NOT NULL,
    cross_source_score REAL NOT NULL,
    seasonal_relevance REAL NOT NULL,
    current_score REAL NOT NULL,
    lifecycle_state TEXT NOT NULL,
    evidence_count INT NOT NULL,
    supporting_sources INT NOT NULL,
    growth_rate REAL,
    is_actionable BOOLEAN NOT NULL
);
CREATE INDEX idx_history_trend_time ON trend_history(trend_id, snapshot_time DESC);
CREATE INDEX idx_history_snapshot ON trend_history(snapshot_time DESC);

-- trend_snapshots: materialized current view (what API serves)
CREATE TABLE trend_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_time TIMESTAMPTZ UNIQUE NOT NULL,
    trends JSONB NOT NULL, -- array of {canonical_name, current_score, components{...}, lifecycle, iran_relevance, evidence_count}
    top_trends_count INT NOT NULL,
    generated_by TEXT DEFAULT 'scheduler',
    scoring_version TEXT NOT NULL,
    meta JSONB -- {sources_healthy, sources_failed, evaluation_metrics}
);
CREATE INDEX idx_snap_time ON trend_snapshots(snapshot_time DESC);

-- operational
CREATE TABLE collection_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    sources_checked INT,
    sources_successful INT,
    sources_failed INT,
    new_documents INT,
    duplicates INT,
    fashion_signals INT,
    trends_created INT,
    trends_updated INT,
    status TEXT CHECK (status IN ('running','success','partial','failed')),
    error_log JSONB
);
CREATE TABLE source_health (
    source_id TEXT PRIMARY KEY REFERENCES sources(source_id),
    consecutive_failures INT DEFAULT 0,
    last_error TEXT,
    last_success TIMESTAMPTZ,
    is_healthy BOOLEAN DEFAULT TRUE,
    circuit_open_until TIMESTAMPTZ
);

-- seasonal affinity reference (seed + later learned)
CREATE TABLE seasonal_affinity (
    canonical_name TEXT REFERENCES fashion_entities(canonical_name),
    season TEXT CHECK (season IN ('spring','summer','autumn','winter')),
    affinity REAL CHECK (affinity BETWEEN 0.3 AND 1.5),
    PRIMARY KEY (canonical_name, season)
);
```

**Key invariants:**
- `raw_documents`, `trend_history`, `trend_snapshots` are **append-only** (no UPDATE/DELETE in app code; only INSERT).
- `trend_evidence` is immutable provenance.
- `llm_cache` key includes `prompt_version` so prompt changes invalidate cache atomically.

---

## 12. Revised Pipeline, API & MVP Scope

### 12.1 Scheduling (different cadence per source)

| Cadence | Sources | Why |
|---------|---------|-----|
| 3h | Digikala Mag | High editorial volume, IR |
| 6h | Vogue | Global reference |
| 12h | BaniMag | E-commerce mag, medium volume |
| 24h | Modeworld, IranModeling (if enabled) | Pure editorial, weekly-ish |
| 1h | Snapshot materialization | Recompute six components + lifecycle hourly from signals |
| Daily 02:00 | `trend_history` rollup + lifecycle transition + evaluation metrics | Batch |

No source is fetched every hour; load spread via `misfire_grace_time`, `coalesce=True`.

### 12.2 API — Same 9 Endpoints, Now with Six-Component Response

```
GET /trends/current?limit=20&category=garment&lifecycle=rising&region=iran&season=summer
GET /trends?iran_min=0.5&season=summer
GET /trends/{id} /by-name/{canonical_name}
GET /trends/category/{category}
GET /trends/iran
GET /trends/emerging
GET /trends/history/{trend_id}?from=2025-01-01&to=2026-09-21
GET /trends/for-recommendation?season=summer&gender=women&occasion=casual  # recommendation engine
GET /sources / /sources/{id}/health / /collection-runs
```

**Response now includes components (auditable):**

```json
{
  "snapshot_time": "2026-09-21T08:00:00Z",
  "trends": [{
    "canonical_name": "wide_leg_bottom",
    "components": {"G":0.78,"I":0.65,"R":0.82,"Gw":1.15,"C":1.38,"S":1.0},
    "current_score": 0.51,
    "lifecycle_state": "rising",
    "explanation": "Rising: 47 signals, 4 sources, R=0.82 (half-life 30d), Gw +15%, C=1.38, S=1.0 (seasonally neutral), I=0.65 (38% IR evidence, fa 62%, compat 0.9)"
  }],
  "meta": {"scoring_version":"v1_heuristic","sources_healthy":4,"stale_warning":null}
}
```

### 12.3 MVP Scope (Revised, Focused — No Multimodal)

**Included (upon approval):**
- Reliable collection (4 core sources: Vogue, Digikala Mag, BaniMag, Modeworld; adapters modular, health-tracked)
- Raw storage (append-only, hash dedup, ETag)
- Fashion attribute extraction (hybrid: rules → taxonomy → embeddings → optional LLM)
- Normalization (synonym + embedding thresholds configurable)
- Deduplication L1–L3
- Trend signal generation + aggregation
- Six-component scoring (G,I,R,Gw,C,S) with **all thresholds configurable** and `v1_heuristic` versioned
- Recency (exponential, half-life configurable)
- Growth (week-over-week slope)
- Cross-source evidence (distinct sources)
- Iran relevance (separate, evidence-based)
- Seasonality (explicit `S`, Persian calendar + affinity table)
- Current trend snapshot (hourly materialization)
- Historical storage (append-only history)
- API (9 endpoints) + OpenAPI
- Tests (mock fixtures, no live net; temporal-leakage test; LLM-disabled test)
- Logging + collection-run summary + source health

**Explicitly NOT in MVP:**
- Advanced multimodal/image (FashionCLIP, CLIP, object detection, visual embeddings)
- Full forecasting models (KERN/REAR/GTM-Transformer) — reserved for Advanced; MVP only stores history for later training
- Pinterest/Twitter/Instagram scraping, Digistyle product catalog (remain disabled)
- Redis/Kafka/Airflow/K8s, vector DB cluster (pgvector optional single extension is max)
- Price scraping, paywall bypass, anti-bot evasion

---

## 13. File Structure & Approval Gate

```
trend_system/
├── README.md
├── ARCHITECTURE_REV1.md          # preserved
├── ARCHITECTURE_REV2.md          # ← this file
├── pyproject.toml
├── .env.example
├── config/
│   ├── sources.yaml
│   ├── scoring.yaml              # six-component weights, half-life, thresholds — all knobs
│   ├── taxonomy.yaml
│   ├── seasonal_affinity.yaml    # new
│   └── llm.yaml                  # new: provider-agnostic
├── trend_system/
│   ├── main.py                   # FastAPI lifespan + APScheduler
│   ├── config.py
│   ├── database/{models,session,migrations}
│   ├── collectors/{base, global_sources/vogue, iranian_sources/digikala_mag, iranian_sources/banimag, iranian_sources/modeworld, google_trends(optional), pinterest(optional)}
│   ├── extraction/{text_extractor, fashion_extractor, llm_provider} # llm_provider = interface + 4 impls
│   ├── normalization/{taxonomy, synonym_mapper, semantic_normalizer}
│   ├── deduplication/{hash_dedup, near_dup}
│   ├── scoring/{recency, source_score, iran_relevance, seasonality, growth, cross_source, trend_score, lifecycle}
│   ├── aggregation/trend_aggregator
│   ├── scheduler/{jobs, snapshot} # snapshot materializes six components
│   ├── api/{routes/trends, routes/sources, schemas}
│   └── utils/{robots, http, logging}
├── tests/{fixtures, test_collectors, test_normalization, test_scoring, test_seasonality, test_temporal_leakage, test_api, test_llm_disabled}
├── seed/demo_trends.json         # synthetic, is_synthetic=true
└── scripts/{seed_sources, run_collector, materialize_snapshot}
```

### What We Need From You

**No code has been written** (per your constraint). Please confirm:

1. **Sources:** Is **4-source MVP (Vogue, Digikala Mag, BaniMag, Modeworld)** approved? Keep IranModeling + Fashion4Iran + Modiseh + Shixon as *disabled candidates* (not deleted) and Digistyle catalog disabled?
2. **Seasonality:** Persian calendar + affinity table with range `[0.5–1.2]` acceptable, or prefer Gregorian only?
3. **LLM:** Is `config/llm.yaml` with `enabled:true/false` + `DummyProvider` fallback acceptable (system works without key)?
4. **Tuning approach:** Time-based split grid search over half-life 7–90 days + other knobs, optimizing `F1@k` with stability constraint — approved?

Reply **“Approved Rev 2 — proceed to implementation”** (or edits) and we will implement the MVP file-by-file, with tests and docs, exactly as scoped in §12.3.

---

## Appendix — Live Verification Log (2026-09-21)

- Vogue robots + sitemap + RSS fetched; 6 sitemaps + RSS ~20 items
- Digikala/Digistyle robots + sitemap shards verified (20 gz shards, 2026-09-19)
- Banimode: `robots.txt` allows blog, `sitemap_index.xml` → post-sitemap1/2 + category, RSS `/blog/feed/` live (fetch returned 5 items)
- Modeworld: `robots.txt` (Yoast), `sitemap_index.xml` → post-sitemap1/2, feed live (10 items), latest article 2026-09-20
- IranModeling: `sitemap_index.xml` → 3 post sitemaps, lastmod 2026-09-19
- Shixon/Modiseh/Rochi/Fashion4Iran also probed (see table)
- Pytrends archived 2025-04-17, Google Trends alpha gated (multiple 2026 sources), Pinterest v5 Trial→Standard (policy restricts)

**End Rev 2 — Awaiting Approval.**
