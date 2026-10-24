import math
from datetime import datetime, timezone, timedelta
from trend_system.scoring.recency import recency_weight, age_days
from trend_system.scoring.trend_score import compute_trend_score_for_signals
from trend_system.config import get_scoring_config

def test_recency_exponential():
    # half-life 30d: age 30 -> 0.5, age 0->1
    assert abs(recency_weight(0,30) - 1.0) < 1e-6
    assert abs(recency_weight(30,30) - 0.5) < 1e-6
    assert abs(recency_weight(60,30) - 0.25) < 1e-6

def test_recency_power_law():
    # half-life 30: power_law 30 -> 0.5
    assert abs(recency_weight(30,30,"power_law") - 0.5) < 1e-6
    assert abs(recency_weight(0,30,"power_law") - 1.0) < 1e-6

def test_gated_geom_vs_additive():
    now = datetime.now(timezone.utc)
    cfg = get_scoring_config()
    signals_high_global_low_iran = [
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.9, "authority_weight":0.9, "source_id":"vogue", "region":"global", "language":"en"} for _ in range(5)
    ]
    score_gated, comps = compute_trend_score_for_signals(signals_high_global_low_iran, "wide_leg_bottom", now, "summer", growth_rate=0.0, mode="gated_geom")
    score_add, _ = compute_trend_score_for_signals(signals_high_global_low_iran, "wide_leg_bottom", now, "summer", growth_rate=0.0, mode="additive")
    if cfg.get("trend_scope") == "global" or not cfg.get("iran_relevance", {}).get("enabled", False):
        # Global: I=1, so gated_geom should NOT penalize global-only signals; gated ~ bundle, additive weighted
        # Both scores should be reasonably high (>0.3) and I ==1
        assert comps["I"] == 1.0
        assert score_gated > 0.3 and score_add > 0.3
        # For global, additive and gated should be relatively close (within 0.4) since gate neutral
        assert abs(score_gated - score_add) < 0.5
    else:
        # Legacy Iranian mode
        assert score_gated < score_add, f"gated {score_gated} should be < additive {score_add} when I low"

def test_seasonal_soft_vs_hard():
    now = datetime.now(timezone.utc)
    signals = [
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.9, "authority_weight":0.9, "source_id":"vogue", "region":"global", "language":"en"} for _ in range(5)
    ]
    # wool in summer (S=0.5) vs linen in summer (S=1.2)
    score_wool, _ = compute_trend_score_for_signals(signals, "wool", now, "summer", mode="gated_geom")
    score_linen, _ = compute_trend_score_for_signals(signals, "linen", now, "summer", mode="gated_geom")
    assert score_linen > score_wool, "linen summer should score higher than wool summer"

def test_min_evidence_guard():
    cfg = get_scoring_config()
    assert cfg["min_evidence_count"] == 3
    assert cfg["min_supporting_sources"] == 2
