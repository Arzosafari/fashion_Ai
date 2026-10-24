"""Global trend scoring.

Formula (``scoring_mode: gated_geom``, verified against the historical
snapshots in ``trends.db``)::

    G      = Σ(w_i · confidence_i · authority_i) / Σ(w_i)      # source quality
    R      = Σ(w_i) / n                                        # freshness
    C      = 1 + ln(1 + distinct_sources) / ln(1 + max_sources)
    C_norm = C / 2
    P      = distinct_days / window_days                       # recurrence
    Gw     = clamp(1 + growth_rate, 0.8, 1.3) / 1.3            # growth (normalized)
    S      = seasonal_affinity / 1.2                           # seasonal (normalized)
    I      = 1.0 for global scope (neutral gate)

    score  = exp( Σ w_k · ln(x_k) / Σ w_k ) · I ** gate_weight

with ``x = {G, C_norm, P, R, Gw_norm, S_norm}`` and weights from
``config/scoring.yaml:bundle_weights``.  ``semantic_consistency`` is reported
in the components for explainability and is *not* multiplied into the score
(same behaviour as the original module).

Freshness half-life (default 30 days) and the similarity threshold are
configurable through ``HALF_LIFE_DAYS`` / ``TREND_SIMILARITY_THRESHOLD``.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

from trend_system.config import get_scoring_config, get_sources_config
from trend_system.scoring.iran_relevance import compute_iran_relevance
from trend_system.scoring.recency import age_days, recency_weight
from trend_system.scoring.seasonality import get_season_affinity

_EPSILON = 1e-6
_DEFAULT_BUNDLE_WEIGHTS = {"G": 1.0, "C": 0.8, "P": 1.0, "R": 1.2, "Gw": 0.7, "S": 0.6}
_DEFAULT_ADDITIVE_WEIGHTS = {"G": 0.25, "C": 0.10, "P": 0.10, "R": 0.20, "I": 0.0, "Gw": 0.05, "S": 0.10}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _enabled_source_count() -> int:
    try:
        sources = get_sources_config().get("sources", [])
        enabled = [s for s in sources if s.get("enabled")]
        return max(1, len(enabled))
    except Exception:
        return 1


def _decay_type(cfg: dict) -> str:
    decay = cfg.get("decay_type")
    if decay:
        return str(decay)
    recency_cfg = cfg.get("recency") or {}
    formula = str(recency_cfg.get("formula", "exponential")).lower()
    if "power" in formula:
        return "power_law"
    return "exponential"


def _half_life(cfg: dict) -> float:
    recency_cfg = cfg.get("recency") or {}
    value = recency_cfg.get("half_life_days", cfg.get("half_life_days", 30))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 30.0


def _semantic_consistency(signals: list[dict], cfg: dict) -> float:
    """Consistency of extracted attributes across evidence sources.

    A constant default (0.85) preserves the historical snapshots; when signals
    carry an explicit ``semantic_consistency`` value (e.g. from the clustering
    step) the mean is used instead.
    """
    explicit = [
        float(s["semantic_consistency"])
        for s in signals
        if isinstance(s.get("semantic_consistency"), (int, float))
    ]
    if explicit:
        return _clamp(sum(explicit) / len(explicit), 0.0, 1.0)
    try:
        return _clamp(float(cfg.get("semantic_consistency_default", 0.85)), 0.0, 1.0)
    except (TypeError, ValueError):
        return 0.85


def compute_trend_score_for_signals(
    signals: list[dict],
    canonical: str,
    now: datetime,
    season: str | None,
    growth_rate: float = 0.0,
    scoring_cfg: dict | None = None,
    mode: str | None = None,
) -> tuple[float, dict]:
    """Compute ``(score, components)`` for one concept.

    ``signals`` must already be filtered to the analysis window and to
    ``timestamp_utc <= now`` (point-in-time correctness is enforced by the
    aggregator/snapshot layer, not here).
    """
    cfg = scoring_cfg if scoring_cfg is not None else get_scoring_config()
    mode = (mode or cfg.get("scoring_mode") or "gated_geom").lower()

    bundle_weights = dict(cfg.get("bundle_weights") or _DEFAULT_BUNDLE_WEIGHTS)
    additive_weights = dict(cfg.get("additive_weights") or _DEFAULT_ADDITIVE_WEIGHTS)

    half_life = _half_life(cfg)
    decay = _decay_type(cfg)
    window_days = float(cfg.get("window_days", 30) or 30)

    valid = [s for s in signals if _as_datetime(s.get("timestamp_utc")) is not None]
    n = len(valid)

    if n == 0:
        components = {
            "G": 0.0, "C": 1.0, "C_norm": 0.5, "P": 0.0, "R": 0.0,
            "Gw": 1.0, "Gw_norm": 1.0 / 1.3, "S": 1.0, "S_norm": 1.0 / 1.2,
            "I": compute_iran_relevance(0.0, 0.0, canonical, None, cfg),
            "semantic_consistency": _semantic_consistency([], cfg), "recurrence": 0.0,
        }
        return _EPSILON, components

    recency_weights: list[float] = []
    weighted_quality = 0.0
    iran_signals = 0
    fa_signals = 0
    days: set = set()

    for signal in valid:
        ts = _as_datetime(signal.get("timestamp_utc"))
        weight = recency_weight(age_days(ts, now), half_life, decay)
        recency_weights.append(weight)

        confidence = signal.get("confidence")
        if confidence is None:
            confidence = 0.5
        authority = signal.get("authority_weight")
        if authority is None:
            authority = 0.5
        try:
            weighted_quality += weight * float(confidence) * float(authority)
        except (TypeError, ValueError):
            weighted_quality += weight * 0.25

        if signal.get("region") == "iranian" or str(signal.get("source_id", "")).lower() in {
            "digikala_mag", "banimode_mag", "modeworld",
        }:
            iran_signals += 1
        if str(signal.get("language", "")).lower() == "fa":
            fa_signals += 1
        days.add(ts.date())

    weight_sum = sum(recency_weights) or _EPSILON
    G = _clamp(weighted_quality / weight_sum, 0.0, 1.0)
    R = _clamp(sum(recency_weights) / n, 0.0, 1.0)

    distinct_sources = len({s.get("source_id") for s in valid if s.get("source_id")})
    max_sources = max(_enabled_source_count(), distinct_sources, 1)
    if max_sources <= 1:
        C = 1.0 + (1.0 if distinct_sources > 1 else 0.0)
    else:
        C = 1.0 + math.log(1.0 + distinct_sources) / math.log(1.0 + max_sources)
    C = _clamp(C, 1.0, 2.0)
    C_norm = C / 2.0

    P = _clamp(len(days) / window_days if window_days > 0 else 0.0, 0.0, 1.0)

    growth_cfg = cfg.get("growth") or {}
    clamp_range = growth_cfg.get("clamp") or [0.8, 1.3]
    try:
        low, high = float(clamp_range[0]), float(clamp_range[1])
    except (TypeError, ValueError, IndexError):
        low, high = 0.8, 1.3
    growth_raw = 1.0 + float(growth_rate or 0.0)
    Gw = _clamp(growth_raw, low, high)
    Gw_norm = _clamp(Gw / high if high else 1.0, 0.0, 1.0)

    S = get_season_affinity(canonical, season)
    seasonal_cfg = cfg.get("seasonal") or {}
    boost_range = seasonal_cfg.get("boost_range") or [0.5, 1.2]
    try:
        S_max = float(boost_range[1])
    except (TypeError, ValueError, IndexError):
        S_max = 1.2
    S_norm = _clamp(S / S_max if S_max else 1.0, 0.0, 1.0)

    I = compute_iran_relevance(
        iran_signals / n, fa_signals / n, canonical, None, cfg
    )
    semantic_consistency = _semantic_consistency(valid, cfg)

    components = {
        "G": round(G, 4),
        "C": round(C, 4),
        "C_norm": round(C_norm, 4),
        "P": round(P, 4),
        "R": round(R, 4),
        "Gw": round(Gw, 4),
        "Gw_norm": round(Gw_norm, 4),
        "S": round(S, 4),
        "S_norm": round(S_norm, 4),
        "I": round(I, 4),
        "semantic_consistency": round(semantic_consistency, 4),
        "recurrence": round(P, 4),
    }

    normalized = {
        "G": max(G, _EPSILON),
        "C": max(C_norm, _EPSILON),
        "P": max(P, _EPSILON),
        "R": max(R, _EPSILON),
        "Gw": max(Gw_norm, _EPSILON),
        "S": max(S_norm, _EPSILON),
    }

    if mode == "additive":
        total_weight = sum(abs(float(w)) for w in additive_weights.values()) or 1.0
        score = 0.0
        for key, weight in additive_weights.items():
            weight = float(weight)
            if key == "I":
                value = I
            else:
                value = normalized.get(key, 0.5)
            score += weight * value
        score = score / total_weight
    elif mode == "multiplicative":
        score = 1.0
        for key in ("G", "C", "P", "R", "Gw", "S"):
            score *= normalized[key]
        gate_weight = float((cfg.get("gate") or {}).get("I_weight", 0.0))
        score *= I ** gate_weight
    else:  # gated_geom (default) or geometric
        total_weight = sum(abs(float(w)) for w in bundle_weights.values()) or 1.0
        log_sum = 0.0
        for key, weight in bundle_weights.items():
            weight = float(weight)
            if weight == 0:
                continue
            value = normalized.get(key)
            if value is None or value <= 0:
                value = _EPSILON
            log_sum += weight * math.log(value)
        score = math.exp(log_sum / total_weight)
        gate_weight = float((cfg.get("gate") or {}).get("I_weight", 0.0))
        if gate_weight:
            score *= I ** gate_weight

    score = _clamp(score, _EPSILON, 1.0)
    return score, components
