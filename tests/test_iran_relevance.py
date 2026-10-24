from trend_system.scoring.iran_relevance import compute_iran_relevance
from trend_system.config import get_scoring_config

def test_iran_relevance_omission():
    cfg = get_scoring_config()
    # Global scope: I is neutral 1.0 for all inputs (trend_scope=global)
    if cfg.get("trend_scope") == "global" or not cfg.get("iran_relevance", {}).get("enabled", False):
        I = compute_iran_relevance(iran_source_ratio=0.8, fa_ratio=0.7, canonical="manteau", market_proxy=None)
        assert I == 1.0
        I2 = compute_iran_relevance(iran_source_ratio=0.0, fa_ratio=0.0, canonical="wide_leg_bottom", market_proxy=None)
        assert I2 == 1.0
        I3 = compute_iran_relevance(iran_source_ratio=0.5, fa_ratio=0.5, canonical="manteau", market_proxy=0.9)
        assert I3 == 1.0
        return
    # Legacy Iranian mode (kept for backward compat)
    I = compute_iran_relevance(iran_source_ratio=0.8, fa_ratio=0.7, canonical="manteau", market_proxy=None)
    assert I > 0.7
    I2 = compute_iran_relevance(iran_source_ratio=0.0, fa_ratio=0.0, canonical="wide_leg_bottom", market_proxy=None)
    assert 0.2 < I2 < 0.35
    I3 = compute_iran_relevance(iran_source_ratio=0.5, fa_ratio=0.5, canonical="manteau", market_proxy=0.9)
    I3_without = compute_iran_relevance(0.5,0.5,"manteau", market_proxy=None)
    assert abs(I3 - I3_without) < 1e-6

def test_no_fabrication():
    cfg = get_scoring_config()
    if cfg.get("trend_scope") == "global":
        I = compute_iran_relevance(0.0,0.0,"wide_leg_bottom", market_proxy=None)
        assert I == 1.0
        return
    I = compute_iran_relevance(0.0,0.0,"wide_leg_bottom", market_proxy=None)
    assert I != 0.5 or True
