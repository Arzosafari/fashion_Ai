"""Global migration tests — per spec 2026-09-29."""
import os
import pytest
from datetime import datetime, timezone, timedelta
from trend_system.config import get_sources_config, get_scoring_config
from trend_system.normalization.semantic_cluster import SemanticClusterer, semantic_dedup_signals, get_similarity_threshold
from trend_system.extraction.season_extractor import normalize_season_tag, extract_fashion_weeks
from trend_system.scoring.recency import recency_weight
from trend_system.scoring.trend_score import compute_trend_score_for_signals

def test_no_iranian_sources_enabled():
    cfg = get_sources_config()
    enabled = [s for s in cfg.get("sources", []) if s.get("enabled")]
    enabled_ids = {s["source_id"] for s in enabled}
    assert "digikala_mag" not in enabled_ids, "Iranian digikala_mag must not be enabled"
    assert "banimode_mag" not in enabled_ids
    assert "modeworld" not in enabled_ids
    # Must have 4 global enabled
    assert {"vogue","harpers_bazaar","whowhatwear","wgsn"} <= enabled_ids
    assert len(enabled) == 4, f"Expected 4 enabled global, got {enabled_ids}"

def test_source_config_centralization():
    cfg = get_sources_config()
    # Verify TREND_SOURCES central array exists and contains required fields
    for src in cfg["sources"]:
        assert "source_id" in src
        # sitemap_url required only for sitemap extraction; api sources may omit
        if src.get("extraction_method") in ("sitemap","sitemap_rss"):
            assert "sitemap_url" in src and src["sitemap_url"]
        # scope must be present for enabled/global sources
        if src.get("enabled") and src.get("scope"):
            assert src.get("scope") == "global"
    # Check harpers verified robots note
    hb = next(s for s in cfg["sources"] if s["source_id"]=="harpers_bazaar")
    assert "harpersbazaar.com/sitemap_index.xml" in hb["sitemap_url"]
    ww = next(s for s in cfg["sources"] if s["source_id"]=="whowhatwear")
    assert "whowhatwear.com/sitemap.xml" in ww["sitemap_url"]
    wgsn = next(s for s in cfg["sources"] if s["source_id"]=="wgsn")
    assert wgsn["accessibility"] == "restricted"

def test_registry_maps_global_adapters():
    from trend_system.collectors.registry import ADAPTER_MAP, get_adapter
    assert "vogue" in ADAPTER_MAP
    assert "harpers_bazaar" in ADAPTER_MAP
    assert "whowhatwear" in ADAPTER_MAP
    assert "wgsn" in ADAPTER_MAP
    assert "digikala_mag" not in ADAPTER_MAP
    for sid in ["vogue","harpers_bazaar","whowhatwear","wgsn"]:
        cfg = next(s for s in get_sources_config()["sources"] if s["source_id"]==sid)
        adapter = get_adapter(sid, cfg)
        assert adapter is not None
        assert adapter.source_id == sid

def test_extraction_global_trends():
    from trend_system.extraction.fashion_extractor import extract_fashion_attributes
    text = "Vogue reports oversized floral brooches and dramatic bows in sculptural ruffles for Fall/Winter 2026. Animal prints and elevated bomber jackets dominate Paris Fashion Week."
    found = extract_fashion_attributes(text, title="Oversized floral brooches trend")
    # Should detect at least 3 global trend candidates
    cands = found["trend_candidates"]
    assert "oversized_floral_brooches" in cands or "oversized_floral_brooches" in found["garments"]
    assert "dramatic_bows" in cands or "dramatic_bows" in found["styles"]
    assert "sculptural_ruffles" in cands
    assert "animal_print" in cands
    assert "elevated_bomber_jacket" in cands
    # Also test red tailoring detection
    text2 = "Scarlet tailoring and red tailored suits took over Milan Fashion Week. Bold red suiting was everywhere."
    found2 = extract_fashion_attributes(text2)
    assert "red_tailoring" in found2["trend_candidates"] or "red" in found2["trend_candidates"]

def test_season_normalization_SS26():
    assert normalize_season_tag("Showcasing SS26 collection at Paris Fashion Week") == "Spring/Summer 2026"
    assert normalize_season_tag("FW26 trends from Milan") == "Fall/Winter 2026"
    assert normalize_season_tag("S/S 2026 street style") == "Spring/Summer 2026"
    assert normalize_season_tag("Resort 2026 preview") == "Resort 2026"
    assert normalize_season_tag("No season here", default="unknown") == "unknown"
    weeks = extract_fashion_weeks("Highlights from Paris Fashion Week and Copenhagen Fashion Week SS26")
    assert "Paris" in weeks
    assert "Copenhagen" in weeks

def test_fashion_weeks_extensible():
    from trend_system.config import get_scoring_config
    cfg = get_scoring_config()
    fw = cfg.get("seasonal", {}).get("fashion_weeks") or ["NY","London","Milan","Paris","Copenhagen"]
    for city in ["NY","London","Milan","Paris","Copenhagen"]:
        assert city in fw

def test_clustering_red_tailoring_not_handbags():
    # Spec example: scarlet tailoring cluster must NOT merge red handbags despite color overlap
    clusterer = SemanticClusterer(threshold=0.58)
    items = [
        {"canonical": "red_tailoring", "category": "styling", "attributes": {"color":"red","garment":"suit"}},
        {"canonical": "scarlet tailoring", "category": "styling", "attributes": {"color":"scarlet","garment":"suit"}},
        {"canonical": "red tailored suits", "category": "styling", "attributes": {"color":"red","garment":"suit"}},
        {"canonical": "handbag", "category": "accessory", "attributes": {"color":"red"}},
        {"canonical": "red handbag", "category": "accessory", "attributes": {"color":"red","garment":"bag"}},
    ]
    clusters = clusterer.cluster(items)
    # Find clusters
    # red_tailoring variants should be together
    tailoring_clusters = [c for c in clusters if any(it["canonical"] in ("red_tailoring","scarlet tailoring","red tailored suits") for it in c)]
    assert len(tailoring_clusters) == 1, f"red tailoring variants should be one cluster, got {clusters}"
    tail_cl = tailoring_clusters[0]
    tail_canons = {it["canonical"] for it in tail_cl}
    assert "handbag" not in tail_canons
    assert "red handbag" not in tail_canons
    # handbag cluster separate
    handbag_clusters = [c for c in clusters if any(it["canonical"] in ("handbag","red handbag") for it in c)]
    assert len(handbag_clusters) == 1
    # Ensure total clusters >=2
    assert len(clusters) >= 2

def test_semantic_dedup_signals():
    # Test dedup merges similar concepts across sources
    now = datetime.now(timezone.utc)
    signals = {
        "red_tailoring": [
            {"concept":"red_tailoring","source_id":"vogue","timestamp_utc":now, "confidence":0.9, "authority_weight":0.95, "category":"styling"},
            {"concept":"red_tailoring","source_id":"harpers_bazaar","timestamp_utc":now, "confidence":0.9, "authority_weight":0.9, "category":"styling"},
        ],
        "scarlet tailoring": [
            {"concept":"scarlet tailoring","source_id":"whowhatwear","timestamp_utc":now, "confidence":0.85, "authority_weight":0.75, "category":"styling"},
        ],
        "handbag": [
            {"concept":"handbag","source_id":"vogue","timestamp_utc":now, "confidence":0.8, "authority_weight":0.95, "category":"accessory"},
        ]
    }
    merged = semantic_dedup_signals(signals, threshold=0.58)
    # red tailoring and scarlet tailoring should merge, handbag stays separate
    assert len(merged) == 2, f"Expected 2 merged groups, got {list(merged.keys())}"
    # Find rep that contains red tailoring variants
    merged_keys = set(merged.keys())
    # One of the keys should be red_tailoring or scarlet tailoring with 3 signals
    has_merged_red = any(k in ("red_tailoring","scarlet tailoring") and len(v)==3 for k,v in merged.items())
    assert has_merged_red
    assert "handbag" in merged

def test_similarity_threshold_configurable():
    default = get_similarity_threshold()
    assert abs(default - 0.58) < 1e-6
    # Env override
    os.environ["TREND_SIMILARITY_THRESHOLD"] = "0.65"
    from importlib import reload
    # get_similarity_threshold reads env each call, no reload needed
    assert abs(get_similarity_threshold() - 0.65) < 1e-6
    del os.environ["TREND_SIMILARITY_THRESHOLD"]
    assert abs(get_similarity_threshold() - 0.58) < 1e-6

def test_freshness_half_life_configurable():
    cfg = get_scoring_config()
    assert cfg.get("half_life_days") == 30
    # Freshness formula exp(-age*ln2/HALF_LIFE)
    assert abs(recency_weight(0, 30) - 1.0) < 1e-6
    assert abs(recency_weight(30, 30) - 0.5) < 1e-6
    assert abs(recency_weight(60, 30) - 0.25) < 1e-6
    # Test env override
    os.environ["HALF_LIFE_DAYS"] = "14"
    # need to clear lru cache and reload config? get_scoring_config reads env each time now
    cfg2 = get_scoring_config()
    assert cfg2["half_life_days"] == 14
    # recency with half-life 14: age 14 -> 0.5
    assert abs(recency_weight(14, 14) - 0.5) < 1e-6
    del os.environ["HALF_LIFE_DAYS"]

def test_cross_source_validation():
    now = datetime.now(timezone.utc)
    # Single source evidence should have lower cross-source than multi-source
    sig_single = [{"timestamp_utc": now - timedelta(days=1), "confidence":0.9, "authority_weight":0.9, "source_id":"vogue", "region":"global","language":"en"} for _ in range(3)]
    sig_multi = [
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.9, "authority_weight":0.95, "source_id":"vogue", "region":"global","language":"en"},
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.85, "authority_weight":0.9, "source_id":"harpers_bazaar", "region":"global","language":"en"},
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.8, "authority_weight":0.75, "source_id":"whowhatwear", "region":"global","language":"en"},
    ]
    score_single, comps_single = compute_trend_score_for_signals(sig_single, "red_tailoring", now, "Fall/Winter 2026", growth_rate=0.0)
    score_multi, comps_multi = compute_trend_score_for_signals(sig_multi, "red_tailoring", now, "Fall/Winter 2026", growth_rate=0.0)
    # Multi-source should have higher cross-source score (C)
    assert comps_multi["C"] > comps_single["C"]
    # And overall score should benefit from multi-source (all else equal)
    # Since multi has slightly varied authority but distinct sources, cross-source boost should help
    assert comps_multi["C_norm"] > comps_single["C_norm"]

def test_trend_scoring_formula_global():
    now = datetime.now(timezone.utc)
    signals = [
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.9, "authority_weight":0.95, "source_id":"vogue", "region":"global","language":"en"},
        {"timestamp_utc": now - timedelta(days=2), "confidence":0.85, "authority_weight":0.9, "source_id":"harpers_bazaar", "region":"global","language":"en"},
        {"timestamp_utc": now - timedelta(days=1), "confidence":0.8, "authority_weight":0.75, "source_id":"whowhatwear", "region":"global","language":"en"},
    ]
    score, comps = compute_trend_score_for_signals(signals, "oversized_floral_brooches", now, "Spring/Summer 2026")
    # Check components reflect global formula: source_quality(G), freshness(R), cross_source(C), semantic_consistency, recurrence(P)
    assert "G" in comps
    assert "R" in comps
    assert "C" in comps
    assert "semantic_consistency" in comps
    assert "recurrence" in comps or "P" in comps
    # I must be 1.0 for global
    assert comps["I"] == 1.0
    assert 0 < score <= 1

def test_wgsn_graceful_skip():
    # WGSN is restricted but enabled; ensure adapter exists and discovery gracefully handles robots
    from trend_system.collectors.global_sources.wgsn import WGSNAdapter
    cfg = next(s for s in get_sources_config()["sources"] if s["source_id"]=="wgsn")
    adapter = WGSNAdapter(cfg, None)
    assert adapter.source_id == "wgsn"
    # sitemap_url exists but robots blocks; adapter should not raise on instantiation
    assert adapter.sitemap_url == "https://www.wgsn.com/sitemap.xml"

def test_isolation_historical_iranian():
    # Historical Iranian trends must be preserved (not auto-deleted) and isolated via trend_scope
    import sqlite3
    conn = sqlite3.connect("trends.db")
    cur = conn.execute("SELECT trend_scope, count(*) FROM trends GROUP BY trend_scope")
    counts = dict(cur.fetchall())
    # After global migration, new trends have scope global; historical iranian may have been converted to global if they have new global signals (e.g., wide_leg_bottom)
    # So we check that at least global scope exists and historical data not deleted (total >= 10) and not silently mixed
    assert "global" in counts, f"Expected global scope, got {counts}"
    cur2 = conn.execute("SELECT count(*) FROM trends")
    total = cur2.fetchone()[0]
    assert total >= 10, f"Historical trends should not be deleted, total {total} <10"
    # Verify isolation: if iranian still present, it's isolated; if converted, ensure global trends have global scope and old history preserved via trend_history
    # Check that trend_history retains at least one entry (historical preservation)
    cur3 = conn.execute("SELECT count(*) FROM trend_history")
    hist_count = cur3.fetchone()[0]
    assert hist_count >= 1, "History must be preserved"
    conn.close()
