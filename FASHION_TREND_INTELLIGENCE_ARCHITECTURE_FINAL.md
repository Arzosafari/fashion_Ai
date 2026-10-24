# Fashion Trend Intelligence Pipeline — FINAL Architecture (Rev 3)
### Approved Rev 2 + Final Adjustments — Build-Ready
**Date:** 2026-09-21 | **Status:** FINAL — Implementation authorized  
**Changes vs Rev 2:** Locked MVP sources (4), market-proxy disabled & omitted (not estimated), scoring comparison (mult. vs additive vs geometric mean) with final v1 choice, dual Gregorian/Jalali date model, market-evidence omission rule, trend-vs-recommendation boundary, full end-to-end check.

> This is the **last architecture document before code**. No further expansion unless a concrete implementation blocker is discovered. All prior docs preserved (`_REV1`, `_REV2`) for traceability.

---

## Table of Contents
1. [Final Adjustments Summary](#1-final-adjustments-summary)
2. [MVP Sources — Locked](#2-mvp-sources--locked)
3. [Scoring Comparison & Final v1 Heuristic](#3-scoring-comparison--final-v1-heuristic)
4. [Date / Calendar — Dual Support](#4-date--calendar--dual-support)
5. [Market Evidence — Omission Not Estimation](#5-market-evidence--omission-not-estimation)
6. [Recommendation Separation & API Boundary](#6-recommendation-separation--api-boundary)
7. [Final End-to-End Architecture Check](#7-final-end-to-end-architecture-check)
8. [Implementation Plan — Immediate Next Steps](#8-implementation-plan)

---

## 1. Final Adjustments Summary

| # | Final Adjustment | How FINAL Addresses It |
|---|------------------|------------------------|
| 1 | **MVP sources:** Vogue, Digikala Mag, BaniMag, Modeworld. Fashion4Iran disabled candidate. Digistyle disabled. | §2 locked. |
| 2 | **Market-proxy:** Optional future signal, **DISABLED** by default; do not estimate. | §5: omitted from `I` calc when unavailable, weights renormalize. |
| 3 | **Scoring:** Compare `G×C×persistence×R×I×Gw×S` vs weighted additive vs weighted geometric mean; explain advantages/disadvantages, stability, low-component behavior; choose final v1 heuristic (not claimed as science), keep configurable. | §3 full comparison + chosen final. |
| 4 | **Date/Calendar:** Support Gregorian + Persian/Jalali; store UTC + Gregorian + Jalali + season + month; internal primary is timezone-aware UTC. | §4 schema + conversion utility. |
| 5 | **Market evidence:** Do not fabricate; omit if unavailable. | §5 rule. |
| 6 | **Recommendation separation:** Trend System answers “what has evidence?”, Rec Engine answers “should this user wear it?”. Trend API returns structured evidence, never decides for a user. | §6 boundary + example payload matching your spec. |
| 7 | **Final check:** Show data flow, adapters, schema, scoring pipeline, scheduling, snapshot, API, integration boundaries, then proceed. | §7 this doc; §8 implementation plan. |

---

## 2. MVP Sources — Locked

**Initial MVP (4 enabled):**

| ID | Name | Region | Type | Authority | Update | Discovery | Status |
|----|------|--------|------|-----------|--------|-----------|--------|
| `vogue` | Vogue | global | magazine | 0.90 | 6h | sitemap `sitemap.xml` → monthly shards + RSS `feed/rss` | **ENABLED** |
| `digikala_mag` | Digikala Magazine | IR | ecommerce_mag | 0.85 | 3h | sitemap `mag/sitemap_index.xml` | **ENABLED** |
| `banimode_mag` | BaniMag | IR | ecommerce_mag | 0.70 | 12h | sitemap `blog/sitemap_index.xml` + RSS `blog/feed/` | **ENABLED** |
| `modeworld` | Modeworld | IR | pure magazine | 0.65 | 24h | sitemap `sitemap_index.xml` + RSS `feed/` | **ENABLED** |

**Disabled candidates (adapters present, `enabled:false`):**
- `iranmodeling` (iranmodeling.net) — licensed model media, sitemap 3 shards lastmod 2026-09-19
- `fashion4iran` — PrestaShop, `blog_sitemap.xml` huge but intermittent 500
- `digistyle` product catalog — explicitly disabled, no market proxy in MVP
- `google_trends`, `pinterest_trends` — supplementary, disabled
- `modiseh`, `shixon`, `rochi` — evaluated, not in MVP (see Rev 2 table for verification logs)

**Diversity achieved:** 1 global + 2 retailer mags (different brand pools) + 1 pure editorial = 4 independent channels, ≥2 IR sources for cross-source Iran evidence.

```yaml
# config/sources.yaml (final)
sources:
  - {source_id: vogue, enabled: true, authority_weight: 0.90, update_frequency: "6h"}
  - {source_id: digikala_mag, enabled: true, authority_weight: 0.85, update_frequency: "3h"}
  - {source_id: banimode_mag, enabled: true, authority_weight: 0.70, update_frequency: "12h"}
  - {source_id: modeworld, enabled: true, authority_weight: 0.65, update_frequency: "24h"}
  - {source_id: iranmodeling, enabled: false}
  - {source_id: fashion4iran, enabled: false}
  - {source_id: digistyle, enabled: false}
  - {source_id: google_trends, enabled: false}
  - {source_id: pinterest_trends, enabled: false}
```

---

## 3. Scoring Comparison & Final v1 Heuristic

> All formulas operate on components normalized to `[0,1]` except `Gw` (growth, clamped `[0.8,1.3]`), `C` (`[1.0, ~1.6]`), `S` (`[0.5,1.2]`). Weights configurable in `config/scoring.yaml`, versioned `v1_heuristic` (not claimed as established science).

### 3.1 Components Recap (six, computed separately)

| Symbol | Name | Range | Meaning |
|--------|------|-------|---------|
| `G` | GLOBAL_TREND_STRENGTH | 0–1 | Authority-weighted evidence strength (global+IR signals) |
| `C` | CROSS_SOURCE_EVIDENCE | 1.0–~1.6 | `1+log(1+distinct)/log(1+max)` diversity bonus |
| `P` | persistence | 0–1 | `active_days / window_days` |
| `R` | RECENCY | 0–1 | Exponential decay `exp(-ln2*age/half_life)` |
| `I` | IRAN_RELEVANCE | 0–1 | Separate, evidence-based (§5) |
| `Gw`| GROWTH | 0.8–1.3 | `(score_t - score_{t-7d})/(score_{t-7d}+ε)` clamped |
| `S` | SEASONAL_RELEVANCE | 0.5–1.2 | Affinity for current season/month (`config/seasonal_affinity.yaml`) |

### 3.2 Candidate Formulas Compared

#### A. Pure Multiplicative (Proposed Baseline)

```
score_mult = G × C_norm × P × R × I × Gw_norm × S_norm
# where C_norm = C/1.6, Gw_norm = Gw/1.3, S_norm = S/1.2 to keep comparable scale,
# or keep raw C,Gw,S and normalize final min-max. Either is multiplicative.
```

| Aspect | Analysis |
|--------|----------|
| **Advantages** | • Natural **AND** gate: every component must be non-zero. Enforces “global is not Iranian” — if `I=0`, final 0 regardless of `G`. <br>• Strong penalization of any failure matches research intuition (exponential decay, cross-source complementarity). <br>• Scale-invariant in log space, no weight tuning needed for basic gate behavior. |
| **Disadvantages** | • **Harsh collapse** — single low component kills entire trend. Example: `G=0.8,C=1.3,P=0.8,R=0.9,Gw=1.1,S=0.5 (off-season)` with `I=0.6` → `0.8*1.3*0.8*0.9*0.6*1.1*0.5 = 0.247` (heavy season penalty). Seasonality is softer than Iran gate, but treated identically. <br>• **Weight inflexibility**: all components equally weighted; cannot say “season is less important than Iran”. <br>• **Numerical underflow** if many small components: 6× 0.3 → 0.0007 still representable in float64 but needs log-space or min-max renormalization to stay distinguishable. |
| **Stability** | Product of 7 numbers in (0,1.6) stays >1e-9 even for low inputs; float64 safe but log transform recommended for ranking stability. |
| **Low-component behavior** | If any component → 0, score → 0. `I=0.05` (no Iranian evidence) → final ≈0 even if `G=0.9` — **desired for Iran gate**, but same behavior for `S=0.5` may be too strict for seasonal. |

#### B. Weighted Additive

```
score_add = wG*G + wC*C_norm + wP*P + wR*R + wI*I + wGw*Gw_norm + wS*S_norm
# Σw = 1, each w configurable
```

| Aspect | Analysis |
|--------|----------|
| **Advantages** | • **Compensatory**: high `G` can compensate low `I` partially; smooth gradients. <br>• **Weights explicit**: tune importance per component. <br>• **Numerically stable**: linear, no underflow, score stays in [0,1] if inputs normalized. |
| **Disadvantages** | • **Breaks Iran gate**: `I=0.05, G=0.9` with `wI=0.2, wG=0.3` → `score ≈ 0.2*0.05+0.3*0.9=0.28` → still moderate rank despite *no Iranian evidence*, contradicting “global ≠ Iranian”. Additive lets global compensate for missing local evidence. <br>• **Violates AND intuition**: trend with `evidence_count=1` (low persistence) but high `G` still scores high, undermining `min_evidence` guard. <br>• Needs many weights (7) to tune; linear weights less intuitive than multiplicative gating. |
| **Stability** | Excellent — addition, no log needed. |
| **Low-component behavior** | Score reduced by `w*low_value`, not collapsed. `I=0` costs only `wI` fraction. For our requirement, too lenient. |

#### C. Weighted Geometric Mean

```
score_geom = ( G^{wG} × C^{wC} × P^{wP} × R^{wR} × I^{wI} × Gw^{wGw} × S^{wS} )^{1/Σw}
# or log form: exp( Σ w_i * log(x_i) / Σw )
# If any x_i=0 → log→ -inf → score 0 unless smoothed (add ε)
```

| Aspect | Analysis |
|--------|----------|
| **Advantages** | • **Multiplicative with tunable weights**: exponents control importance; `wI=2.0` makes Iran gate stronger than `wS=0.5`. Balances AND vs compensation. <br>• **Scale-invariant**, **diminishing returns** built-in. <br>• **Log-space computation** numerically stable; handle zero via `max(x, ε)` smoothing. |
| **Disadvantages** | • Still collapses if any component =0 (unless ε-smoothed). <br>• Less intuitive to explain than pure product; exponents vs linear weights mental model harder. <br>• Requires `ε` (e.g., 1e-6) to avoid log(0). |
| **Stability** | **Best** — compute in log space, no underflow even for many small components. |
| **Low-component behavior** | Penalizes low but weighted: `I=0.05` with `wI=2` collapses more than `S=0.5` with `wS=0.5`. Controllable. |

### 3.3 Comparison Summary

| Criterion | Multiplicative | Additive | Geometric Mean |
|-----------|----------------|----------|----------------|
| **Enforces Iran gate (global≠Iran)** | ✅ Yes (hard gate) | ❌ No (compensatory) | ✅ Yes (with high wI) |
| **Tunable importance per component** | ❌ No (equal) | ✅ Yes (linear) | ✅ Yes (exponents) |
| **Seasonal soft penalty vs hard gate** | ❌ Treats S like I | ✅ Soft | ✅ Soft if wS low |
| **Numerical stability** | Good (needs log for many lows) | Excellent | Excellent (log space) |
| **Collapse on zero** | Hard 0 | Never 0 | Hard 0 (unless ε) |
| **Explainability** | “Product of components” — simple | “Weighted sum” — simple | “Weighted product in log space” — harder |
| **Meets “do not compensate missing evidence”** | ✅ | ❌ | ✅ (if wI high) |

### 3.4 Final v1 Heuristic Decision

**Chosen: Hybrid — “Gated Geometric Mean”**

We keep the **spirit of multiplicative gating** (Iran must have evidence) but gain **weight tunability** and **soft seasonal penalty** via weighted geometric mean for the *global/seasonal/trend* components, with **Iran relevance as a separate multiplicative gate**.

```
# Step 1: GlobalTrendBundle (without Iran) as weighted geometric mean
bundle = ( G^{wG} × C_norm^{wC} × P^{wP} × R^{wR} × Gw_norm^{wGw} × S_norm^{wS} )^{1/(wG+wC+wP+wR+wGw+wS)}

# Step 2: Gate by Iran relevance (not averaged away)
current_score = bundle × I^{wI_gate}
# where wI_gate is typically 1.0 (full gate) — if I=0.05, final ≈ bundle*0.05
# Alternative form equivalently: geometric mean of all 7 with wI larger (e.g., wI=2) and no extra gate,
# but explicit gate makes Iran separation visible in API (components.I separate).

# Numerical implementation: compute in log space
log_bundle = (wG*log(G+ε) + wC*log(C_norm+ε) + ... + wS*log(S_norm+ε)) / Σw_bundle
bundle = exp(log_bundle)
current_score = bundle * (I + ε)^{wI_gate}   # ε=1e-6 to avoid log(0) but gate still strong
current_score = clamp(current_score, 0, 1)
# Then min-max normalize across all trends for ranking (optional)
```

**Defaults (configurable, documented as heuristic):**

```yaml
scoring:
  version: "v1_heuristic_gated_geom"
  window_days: 30
  min_evidence_count: 3
  min_supporting_sources: 2
  half_life_days: 30          # engineering default, tunable via §9
  decay_type: "exponential"
  bundle_weights:            # for G,C,P,R,Gw,S geometric mean
    G: 1.0
    C: 0.8
    P: 1.0
    R: 1.2                    # recency slightly higher
    Gw: 0.7
    S: 0.6                    # seasonal softer
  gate:
    I_weight: 1.0             # full multiplicative gate; 1.0 = linear gate, 2.0 = quadratic stronger gate
  thresholds:
    epsilon: 1.0e-6
    clamp_gw: [0.8, 1.3]
    clamp_s: [0.5, 1.2]
  lifecycle: {...}            # as Rev 2
```

**Why this over pure multiplicative?**
- Retains **Iran gate** (requirement) — low `I` still collapses score, unlike additive.
- **Solves harsh seasonality**: `S=0.5` with `wS=0.6` penalizes less than pure product (where `S=0.5` halves score regardless of other strengths). Now `S` influence is exponent-weighted.
- **Weights are configurable** per feedback — we can tune via historical evaluation without claiming optimality.
- **Numerically stable** in log space, no underflow.
- **Explainable**: API returns both `bundle` and `I` separately; explanation says “global bundle 0.72 × Iran relevance 0.71 = 0.51” — satisfies recommendation separation.

**Why not pure additive?** It lets `G=0.9` hide `I=0.05` — exactly what feedback says **not to do** (global ≠ Iranian). Additive is reserved for ablation study only.

**Why not pure geometric mean of all 7 equally?** It would treat `S` and `I` identically, but requirements state they should be **separate** and `I` is a gate. Our hybrid makes `I` visibly separate.

**Configuration allows all three modes for ablation:**
```yaml
scoring_mode: "gated_geom"  # options: "multiplicative" | "additive" | "geometric" | "gated_geom"
```
Implementation supports switching via `config/scoring.yaml` without code change; evaluation (§9) will compare all three on historical data.

**All weights remain engineering parameters**, versioned `v1_heuristic_gated_geom`, never presented as established science.

---

## 4. Date / Calendar — Dual Support

> Feedback #4: Primary internal timestamp timezone-aware, unambiguous; store both calendars.

### 4.1 Storage Model

| Column | Type | Content | Example |
|--------|------|---------|---------|
| `*timestamp_utc` | `TIMESTAMPTZ` | **Primary, authoritative, UTC, timezone-aware** | `2026-09-21 04:30:00+00` |
| `*_gregorian` | `DATE` + `TIME` or `TIMESTAMPTZ` | Gregorian calendar view (derived, indexed for Gregorian queries) | `2026-09-21` |
| `*_jalali` | `TEXT` or `DATE` | Jalali date `YYYY-MM-DD` + `jalali_month`, `jalali_season` | `1405-06-30` , month `Shahrivar`, season `summer` |
| `season` | `TEXT` | Derived season (both calendars map to same Tehran meteorological season) | `summer` |
| `month` | `INT` | Gregorian month 1–12 + `jalali_month` 1–12 | `9` / `6` |

**Utility:**

```python
# utils/calendar.py
from datetime import datetime, timezone
import jdatetime  # or khayyam, verified

def to_jalali(dt_utc: datetime) -> dict:
    # dt_utc is timezone-aware UTC
    jd = jdatetime.datetime.fromgregorian(datetime=dt_utc)
    return {
        "jalali_date": jd.strftime("%Y-%m-%d"),  # 1405-06-30
        "jalali_year": jd.year,
        "jalali_month": jd.month,               # 1=Farvardin
        "jalali_day": jd.day,
        "jalali_month_name": jd.j_months_fa[jd.month-1],
        "season": jalali_season(jd.month),      # 1-3=spring, 4-6=summer, 7-9=autumn, 10-12=winter
        "season_fa": ...,
        "gregorian_date": dt_utc.date().isoformat(),
        "gregorian_month": dt_utc.month,
        "timestamp_utc": dt_utc.astimezone(timezone.utc).isoformat()
    }
```

**Where used:**
- `raw_documents.publication_date_utc` (primary) + `publication_date_jalali` (computed at ingest)
- `trend_signals.timestamp_utc` + `timestamp_jalali`
- `trend_history.snapshot_time_utc` + `jalali`
- `trend_snapshots.snapshot_time_utc` + `jalali`
- API returns both: `last_updated_utc` + `last_updated_jalali` + `season` + `month`

**Primary invariant:** All scoring, decay, window calculations use **`timestamp_utc`** only — dual calendar is for display, filtering (`?season=summer&calendar=jalali`), and seasonal affinity (which reads `jalali_month` when `season_calendar=persian`).

---

## 5. Market Evidence — Omission Not Estimation

> Feedback #2 & #5: Do not fabricate; omit if unavailable.

**Rule:**

```python
# scoring/iran_relevance.py
def compute_iran_relevance(iran_source_ratio, fa_ratio, compatibility, market_proxy_optional):
    # market_proxy is None when disabled or unavailable
    components = []
    weights = []
    components.append(iran_source_ratio); weights.append(w_iran)
    components.append(fa_ratio);         weights.append(w_fa)
    components.append(compatibility);    weights.append(w_norms)
    if market_proxy_optional is not None:          # only if enabled AND available
        components.append(market_proxy_optional); weights.append(w_market)
        # w = [0.40,0.20,0.25,0.15] as Rev 2
    else:
        # OMIT — renormalize remaining weights to sum 1
        # 0.40+0.20+0.25=0.85 → divide each by 0.85
        weights = [w / sum(weights) for w in weights]
        # so effective w_iran≈0.47, w_fa≈0.235, w_norms≈0.294
    I = sum(c*w for c,w in zip(components, weights))
    return clamp(I, 0, 1)
```

- `config/scoring.yaml: iran_relevance.w_market` commented out or `enabled: false` by default in MVP.
- No `0.5` baseline estimate; **absence = no term**.
- If later a reliable market source (e.g., Digistyle product counts with explicit research justification) is enabled, set `enabled: true` and `w_market` becomes active without code change.

---

## 6. Recommendation Separation & API Boundary

> Feedback #6: Trend System ≠ Recommendation Engine.

### 6.1 System Boundary Diagram

```
┌─────────────────────────────────┐         ┌──────────────────────────────────┐
│ Trend Intelligence System       │         │ Recommendation Engine            │
│ (this pipeline)                 │         │ (separate service, user-specific)│
│                                 │         │                                  │
│ Q: "What trends have evidence?" │─API───► │ Q: "Should THIS user wear it?"   │
│                                 │  JSON   │                                  │
│ - No user profile               │         │ - User wardrobe, style, body,    │
│ - No wardrobe                   │         │   preferences                      │
│ - No weather for outfit (only   │         │ - Wardrobe compatibility         │
│   for seasonal relevance)       │         │ - Weather API for outfit         │
│ - No occasion                   │         │ - Occasion                       │
│ - No personalization            │         │ - Trend as ONE weighted factor   │
│                                 │         │   (≈0.15)                        │
└─────────────────────────────────┘         └──────────────────────────────────┘
```

### 6.2 Trend API Returns Evidence, Not Decisions

**Your requested structure (matched exactly, camelCase vs snake_case configurable):**

```json
{
  "trend": "wide_leg_pants",
  "trend_score": 0.78,
  "iran_relevance": 0.71,
  "lifecycle": "rising",
  "confidence": 0.84,
  "last_updated": "2026-09-21T08:00:00Z",
  "evidence_count": 12,
  "jalali_date": "1405-06-30",
  "season": "summer"
}
```

**Actual MVP endpoint `GET /trends/for-recommendation` returns array of such objects plus components for transparency:**

```json
{
  "snapshot_time_utc": "2026-09-21T08:00:00Z",
  "snapshot_time_jalali": "1405-06-30",
  "season": "summer",
  "trends": [
    {
      "trend": "wide_leg_pants",
      "canonical_name": "wide_leg_bottom",
      "category": "silhouette",
      "trend_score": 0.51,
      "iran_relevance": 0.71,
      "global_strength": 0.78,
      "lifecycle": "rising",
      "confidence": 0.84,
      "last_updated": "2026-09-21T08:00:00Z",
      "last_updated_jalali": "1405-06-30",
      "evidence_count": 47,
      "supporting_sources": 4,
      "seasonal_relevance": 1.0,
      "growth": 1.15,
      "is_actionable": true,
      "components": {"G":0.78,"C":1.38,"P":0.82,"R":0.82,"Gw":1.15,"S":1.0,"I":0.71},
      "top_evidence": [
        {"source_id":"vogue","title":"The Wide-Leg Takeover","url":"https://www.vogue.com/...","date_utc":"2026-09-18","date_jalali":"1405-06-27"},
        {"source_id":"digikala_mag","title":"شلوار گشاد ترند امسال","url":"https://www.digikala.com/mag/...","date_utc":"2026-09-19","date_jalali":"1405-06-28"}
      ]
    }
  ],
  "meta": {"scoring_version":"v1_heuristic_gated_geom","scoring_mode":"gated_geom","sources_healthy":4}
}
```

**Critical rule:** Trend System **never** decides `user should wear X`. It only provides `trend_score` + `iran_relevance` + `lifecycle` + `evidence`. Recommendation Engine decides weighting (e.g., `trend_weight=0.15`, personal taste overrides).

---

## 7. Final End-to-End Architecture Check

### 7.1 Data Flow (FINAL)

```
INTERNET (4 MVP sources + 4 disabled candidates)
   │
   ├─► [Collector Adapters] ── robots.txt check ── ETag/Last-Modified cache ── httpx + tenacity retry ──►
   │
   ▼
RAW STORAGE (PostgreSQL, append-only)
  raw_documents {source_url, content_html, content_text, publication_date_utc + jalali, collection_date_utc, language, content_hash, metadata, is_synthetic}
   │
   ▼
CLEANING (trafilatura, fasttext langdetect, dateparser → UTC + Jalali conversion)
   │
   ▼
DEDUPLICATION
  L1 exact URL (unique constraint) → L2 SHA256 hash → L3 SimHash (>0.85 near-dup) → flag semantic dup (>0.93) for review
  (Independent same-trend from different sources is NOT deduped — it boosts C)
   │
   ▼
CONTENT EXTRACTION
  title, body, date_utc/jalali, image_urls (stored only URLs), author, category
   │
   ▼
FASHION ATTRIBUTE EXTRACTION (hybrid, provider-agnostic)
  1) rules/regex (Persian gazetteers) → 2) taxonomy/synonym → 3) embeddings (multilingual MiniLM, optional pgvector) → 4) LLM (cached, structured, schema-validated, DummyProvider if no key)
   │
   ▼
NORMALIZATION (taxonomy + embedding cosine >0.82 auto, 0.70–0.82 LLM, <0.70 new candidate)
  → fashion_entities.canonical_name (e.g., "شلوار گشاد" → wide_leg_bottom)
   │
   ▼
TREND SIGNAL GENERATION (one signal per concept per doc)
  trend_signals {concept, source_id, raw_document_id, timestamp_utc+jalali, confidence, region}
   │
   ▼
TREND AGGREGATION (group by concept, window W=30d, only timestamp_utc <= snapshot_time_utc)
   │
   ▼
SCORING PIPELINE (six components, §3)
  ┌─────────────────────────────────────────────────────────────────┐
  │ For each concept c:                                             │
  │  G = Σ conf*authority / norm                                    │
  │  C = 1+log(1+distinct)/log(1+max)                               │
  │  P = active_days / W                                            │
  │  R = exp(-ln2*age/half_life) aggregated                         │
  │  Gw = slope vs 7d ago clamped                                   │
  │  S = affinity(c, jalali_month) [persian calendar]               │
  │  I = w1*iran_ratio + w2*fa_ratio + w3*compat (+ w4*market? omit if None) │
  │  bundle = geom_mean(G,C,P,R,Gw,S) in log space                  │
  │  current_score = bundle * I^{wI_gate} → min-max norm 0–1      │
  │  lifecycle from thresholds → trends table                        │
  └─────────────────────────────────────────────────────────────────┘
   │
   ├─► TRENDS (one row per canonical, with 7 columns: G,I,R,Gw,C,S,current_score + lifecycle + evidence_count)
   ├─► TREND_EVIDENCE (provenance many-to-many, snippet for explanation)
   ├─► TREND_HISTORY (append-only, per snapshot_time_utc + jalali, 7 components)
   └─► ► CURRENT SNAPSHOT (hourly materialization: trend_snapshots JSONB, what API serves <50ms)
            │
            ▼
         API BOUNDARY (FastAPI /api/v1)
            │
            ├─► GET /trends/current?season=summer&calendar=jalali
            ├─► GET /trends/for-recommendation (evidence-only, for Rec Engine)
            ├─► GET /trends/history/{id}?from=...&to=...
            ├─► GET /sources/health
            └─► (OpenAPI /docs)
                    │
                    ▼
         RECOMMENDATION ENGINE BOUNDARY (separate)
            Trend API JSON → Rec Engine weights: 0.35 wardrobe + 0.20 user_style + 0.15 weather + 0.15 occasion + 0.15*trend_score*I
            Trend NEVER overrides user preference.
```

### 7.2 Source Adapters

```
collectors/base.py
  BaseCollector (ABC): can_fetch() [robots+health+enabled], discover_urls(), fetch_document(), collect() with retry/backoff/ETag

collectors/global_sources/
  vogue.py → VogueAdapter (sitemap + RSS, 6 sitemaps + feed/rss)

collectors/iranian_sources/
  digikala_mag.py → DigikalaMagAdapter (sitemap_index)
  banimag.py      → BaniMagAdapter (sitemap_index + RSS feed)
  modeworld.py    → ModeworldAdapter (sitemap_index + feed)

collectors/optional/
  google_trends.py (TrendspyAdapter, disabled)
  pinterest.py     (OptionalPinterestAdapter, disabled)
  fashion4iran.py, iranmodeling.py, digistyle.py (disabled candidates)

SourceRegistry: loads config/sources.yaml, instantiates enabled adapters, exposes health.
Adding new source = YAML entry + subclass.
```

### 7.3 Database Schema (FINAL DDL Summary)

> Primary keys, indexes, and append-only invariants as Rev 2, plus Jalali columns + market omission.

```sql
-- sources (4 enabled, 5 disabled)
CREATE TABLE sources (... authority_weight, enabled, sitemap_url, rss_url, ...);

-- raw_documents (append-only)
CREATE TABLE raw_documents (
  id BIGSERIAL PRIMARY KEY,
  source_id TEXT REFERENCES sources,
  source_url TEXT UNIQUE NOT NULL,
  title TEXT, content_html TEXT, content_text TEXT NOT NULL,
  publication_date_utc TIMESTAMPTZ,
  publication_date_jalali TEXT, -- 1405-06-30 (derived)
  publication_season TEXT, publication_jalali_month INT, publication_gregorian_month INT,
  collection_date_utc TIMESTAMPTZ DEFAULT NOW(),
  language TEXT, author TEXT, category TEXT,
  image_urls JSONB, metadata JSONB, content_hash CHAR(64) NOT NULL,
  is_duplicate BOOLEAN, duplicate_of BIGINT, is_synthetic BOOLEAN
);

-- fashion_entities (canonical, with iran_compatibility + ideal_temp_range)
CREATE TABLE fashion_entities (
  canonical_name TEXT PRIMARY KEY,
  category TEXT, aliases JSONB, embedding VECTOR(384),
  iran_compatibility REAL, ideal_temp_range JSONB
);

-- llm_cache (provider-agnostic cache)
CREATE TABLE llm_cache (
  cache_key CHAR(64) PRIMARY KEY,
  prompt_version TEXT, provider_model TEXT, input_hash CHAR(64),
  output_json JSONB, created_at TIMESTAMPTZ, hit_count INT
);

-- fashion_observations
CREATE TABLE fashion_observations (
  id BIGSERIAL PRIMARY KEY,
  raw_document_id BIGINT REFERENCES raw_documents,
  source_id TEXT, entity_id TEXT REFERENCES fashion_entities,
  raw_term TEXT, canonical_name TEXT, category TEXT,
  confidence REAL, extractor_type TEXT CHECK (extractor_type IN ('rule','ner','embedding','llm','vision')),
  span_text TEXT, attributes JSONB, observed_at TIMESTAMPTZ, region TEXT,
  llm_cache_key CHAR(64) REFERENCES llm_cache
);

-- trend_signals (timestamp dual)
CREATE TABLE trend_signals (
  id BIGSERIAL PRIMARY KEY,
  concept TEXT REFERENCES fashion_entities,
  source_id TEXT, observation_id BIGINT, raw_document_id BIGINT,
  timestamp_utc TIMESTAMPTZ NOT NULL,
  timestamp_jalali TEXT, jalali_month INT, season TEXT,
  evidence_type TEXT, confidence REAL, region TEXT
);

-- trends (six components separate + final, versioned)
CREATE TABLE trends (
  canonical_name TEXT PRIMARY KEY REFERENCES fashion_entities,
  category TEXT,
  global_score REAL, iran_relevance_score REAL, recency_score REAL,
  growth_score REAL, cross_source_score REAL, seasonal_relevance REAL,
  current_score REAL, lifecycle_state TEXT,
  first_seen_utc TIMESTAMPTZ, first_seen_jalali TEXT,
  last_seen_utc TIMESTAMPTZ, last_seen_jalali TEXT, updated_at TIMESTAMPTZ,
  evidence_count INT, supporting_sources INT, is_actionable BOOLEAN,
  recommendation_payload JSONB, explanation TEXT, scoring_version TEXT
);

-- trend_evidence (provenance, snippet)
CREATE TABLE trend_evidence (
  id BIGSERIAL PRIMARY KEY,
  trend_id TEXT REFERENCES trends(canonical_name),
  source_id TEXT, observation_id BIGINT, signal_id BIGINT, raw_document_id BIGINT,
  evidence_type TEXT, confidence REAL, timestamp_utc TIMESTAMPTZ, timestamp_jalali TEXT, snippet TEXT
);

-- trend_history (append-only, dual dates, 7 components)
CREATE TABLE trend_history (
  id BIGSERIAL PRIMARY KEY,
  trend_id TEXT REFERENCES trends,
  snapshot_time_utc TIMESTAMPTZ NOT NULL, snapshot_time_jalali TEXT,
  jalali_month INT, season TEXT,
  global_score REAL, iran_relevance_score REAL, recency_score REAL,
  growth_score REAL, cross_source_score REAL, seasonal_relevance REAL,
  current_score REAL, lifecycle_state TEXT, evidence_count INT, supporting_sources INT,
  growth_rate REAL, is_actionable BOOLEAN
);

-- trend_snapshots (materialized, what API serves)
CREATE TABLE trend_snapshots (
  snapshot_time_utc TIMESTAMPTZ PRIMARY KEY,
  snapshot_time_jalali TEXT, season TEXT,
  trends JSONB NOT NULL, top_trends_count INT, generated_by TEXT, scoring_version TEXT, scoring_mode TEXT, meta JSONB
);

-- seasonal_affinity (seed 0.5–1.2)
CREATE TABLE seasonal_affinity (canonical_name TEXT, season TEXT, affinity REAL, PRIMARY KEY (canonical_name, season));

-- operational
CREATE TABLE collection_runs (...);
CREATE TABLE source_health (...);
```

**Invariants:** `raw_documents`, `trend_history`, `trend_snapshots` append-only (no UPDATE/DELETE); `trend_evidence` immutable; queries always `WHERE timestamp_utc <= snapshot_time_utc` to prevent leakage.

### 7.4 Scoring Pipeline (FINAL)

```
signals in W (30d, timestamp_utc <= snapshot_utc)
  │
  ├─► G (authority-weighted) ──┐
  ├─► C (distinct sources)     │
  ├─► P (active_days/W)        ├─► log bundle = Σ w*log(x+ε)/Σw → bundle = exp(log bundle) ──┐
  ├─► R (exp decay, half_life) │                                                    │
  ├─► Gw (7d slope clamped)    │                                                    ├─► current_score = bundle × I^{wI_gate}
  ├─► S (jalali affinity) ─────┘                                                    │         (I from §5 omission rule)
  └─► I (separate, omission) ───────────────────────────────────────────────────────┘
                                                        │
                                                        ├─► lifecycle state machine (thresholds)
                                                        ├─► is_actionable (evidence≥3 && sources≥2)
                                                        ├─► explanation from counts
                                                        └─► min-max norm → trends.current_score
```

All weights/thresholds in `config/scoring.yaml`, `scoring_mode` switchable (`gated_geom` default, `multiplicative|additive|geometric` for ablation).

### 7.5 Update / Scheduling Mechanism

| Job | Schedule | What It Does |
|-----|----------|--------------|
| `collect_vogue` | 6h | discover via sitemap+RSS → fetch → raw append → dedup → extract → signals |
| `collect_digikala_mag` | 3h | sitemap discover → … |
| `collect_banimag` | 12h | sitemap+RSS |
| `collect_modeworld` | 24h | sitemap |
| `materialize_snapshot` | 1h | aggregate W signals → six components → bundle×I → history INSERT → snapshot UPSERT (JSONB) |
| `nightly_rollup` | daily 02:00 UTC | lifecycle transitions, stale detection, evaluation metrics |

**Implementation:** `APScheduler` `BackgroundScheduler` with `SQLAlchemyJobStore` (Postgres), `max_instances=1`, `coalesce=True`, `misfire_grace_time=300`, staggered at :00, :15, :30. Failure: per-source try/except, `tenacity` 3× exp backoff, circuit breaker `circuit_open_until = now + 2^{failures} *1h`, snapshot still serves stale data with `Warning: snapshot stale` header, **never delete valid trends on source failure**.

**Caching:** URL unique → skip; SHA256 hash → skip extraction; `ETag`/`Last-Modified` → `If-None-Match` → 304; sitemap cached `update_frequency/2`; LLM cached by `content_hash+prompt_version`.

### 7.6 Current Snapshot Mechanism

- Hourly job aggregates **only signals with `timestamp_utc <= snapshot_time_utc`** (leakage-proof).
- Computes six components + `current_score` per concept.
- Inserts `trend_history` row per trend (append-only time series).
- Materializes `trend_snapshots` row: `trends` JSONB sorted by `current_score`, `top_trends_count`, `scoring_version`, `scoring_mode`.
- API serves `trend_snapshots` row directly (<50ms, no scoring at request time). If snapshot age > `2*interval`, serve last row with `stale_warning`.
- History preserved forever → enables growth/decay/seasonality/recurrence forecasting later.

### 7.7 API Boundary & Recommendation-Engine Integration Boundary

**Trend API (this system, FastAPI `/api/v1`):**

```
GET /trends/current?limit=20&category=garment&lifecycle=rising&region=iran&season=summer&calendar=jalali
GET /trends/for-recommendation?season=summer&gender=women&limit=10  → returns your requested evidence structure
GET /trends/history/{trend_id}?from=2025-01-01&to=2026-09-21
GET /trends/by-name/{canonical_name}
GET /sources/health
```

Returns **evidence**, never user decisions. Example in §6.2 matches your spec exactly plus `components` for transparency.

**Recommendation Engine (separate, not built here):**

```
inputs = user_profile + wardrobe (items) + weather API + occasion + trends_from_api
trend_factor = trends_api[i].trend_score * trends_api[i].iran_relevance * seasonal_match
final_outfit_score = 0.35*wardrobe_compat + 0.20*user_style + 0.15*weather + 0.15*occasion + 0.15*trend_factor
# Trend NEVER overrides user taste; max boost is bounded.
```

**Boundary contract:** Trend API is **read-only, evidence-providing**; Rec Engine is **personalization & decision-making**. Trend API has no access to user data; Rec Engine has no scraping logic.

---

## 8. Implementation Plan

**This FINAL doc is the build spec. No further architecture expansion needed.**

**Immediate implementation steps (upon this doc’s approval — which you just gave):**

1. Scaffold `trend_system/` per §7 file structure, `pyproject.toml`, `.env.example`, `config/*.yaml` (sources, scoring, taxonomy seed, seasonal_affinity, llm).
2. Database: `models.py` DDL (§7.3) + Alembic migration + `session.py` + seed sources.
3. Collectors: `base.py` + `vogue.py`, `digikala_mag.py`, `banimag.py`, `modeworld.py` with robots, ETag, sitemap+RSS.
4. Extraction: `text_extractor.py` (trafilatura), `fashion_extractor.py` (rules+gazetteers), `llm_provider.py` (interface+DummyProvider, caching).
5. Normalization + dedup (hash, SimHash) + seasonal affinity + calendar utils (`jdatetime`).
6. Scoring pipeline `trend_score.py` supporting `gated_geom | multiplicative | additive | geometric` with log-space, plus `iran_relevance.py` omission logic, `recency.py`, `seasonality.py`, `lifecycle.py`.
7. Scheduler `jobs.py` + `snapshot.py` (hourly materialization, dual dates).
8. API `routes/trends.py` returning evidence structure (§6.2) + OpenAPI.
9. Tests: fixtures (mock HTML/RSS fa+en), `test_temporal_leakage.py`, `test_scoring_modes.py`, `test_llm_disabled.py`, `test_api.py`.
10. Demo data `seed/demo_trends.json` (`is_synthetic=true`) + `README.md` with install/run instructions.

**We will proceed file-by-file now, starting with project scaffold and database — no additional architecture docs unless a blocker appears.**

---
**End FINAL Architecture — Authorized for MVP Implementation.**
