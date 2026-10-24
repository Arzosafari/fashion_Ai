from __future__ import annotations
from datetime import datetime, timedelta
from trend_system.config import get_scoring_config
from trend_system.utils.calendar import to_jalali_dict
from trend_system.scoring.trend_score import compute_trend_score_for_signals
from trend_system.scoring.lifecycle import determine_lifecycle

def aggregate_trends(signals_by_concept: dict, now: datetime, scoring_cfg: dict | None=None, history_map: dict | None=None) -> list[dict]:
    """signals_by_concept: {canonical: [signal_dict,...]} where each signal has timestamp_utc <= now
       history_map: {canonical: [history rows sorted]} for growth
    Returns list of trend dicts ready to upsert.
    """
    cfg = scoring_cfg or get_scoring_config()
    window_days = cfg.get("window_days",30)
    window_start = now - timedelta(days=window_days)
    results=[]
    jalali_now = to_jalali_dict(now)
    season = jalali_now["season"] if cfg.get("seasonal",{}).get("calendar")=="persian" else _gregorian_season(now.month)

    for canonical, signals in signals_by_concept.items():
        # filter window and leakage-proof: only <= now
        in_window = [s for s in signals if s["timestamp_utc"] <= now and s["timestamp_utc"] >= window_start]
        if not in_window:
            continue
        # growth from history if available
        growth_rate = 0.0
        if history_map and canonical in history_map and len(history_map[canonical])>=2:
            # last two snapshots
            hist = sorted(history_map[canonical], key=lambda x: x["snapshot_time_utc"], reverse=True)
            if len(hist)>=2:
                prev = hist[1]["current_score"] if hist[1]["current_score"] else 1e-6
                curr_hist = hist[0]["current_score"] if hist[0]["current_score"] else 0
                growth_rate = (curr_hist - prev) / (prev + 1e-6) if prev>0 else 0
            else:
                growth_rate = 0
        score, comps = compute_trend_score_for_signals(in_window, canonical, now, season, growth_rate, cfg)
        # evidence stats
        evidence_count = len(in_window)
        supporting_sources = len(set(s["source_id"] for s in in_window))
        # persistence
        days = set(s["timestamp_utc"].date() for s in in_window)
        persistence = len(days)/window_days
        # first/last
        first_seen = min(s["timestamp_utc"] for s in in_window)
        last_seen = max(s["timestamp_utc"] for s in in_window)
        age_first = (now - first_seen).total_seconds()/86400
        age_last = (now - last_seen).total_seconds()/86400
        lifecycle = determine_lifecycle(evidence_count, supporting_sources, score, growth_rate, persistence, age_first, age_last, cfg)
        is_actionable = evidence_count >= cfg.get("min_evidence_count",3) and supporting_sources >= cfg.get("min_supporting_sources",2)
        # explanation — global scope neutral, show cross-source validation and freshness
        if cfg.get("trend_scope") == "global" or not cfg.get("iran_relevance", {}).get("enabled", False):
            explanation = f"{canonical} is {lifecycle} based on {evidence_count} signals from {supporting_sources} independent global sources in last {window_days} days, with recency R={comps['R']:.2f} (half-life {cfg.get('half_life_days')}d, decay exp), growth {growth_rate:+.1%}, cross-source {comps['C']:.2f} (semantic {comps.get('semantic_consistency', 0.85):.2f}), seasonal {comps['S']:.2f}. Trend scope global (sources: {', '.join(sorted(set(s['source_id'] for s in in_window)))[:80]})."
        else:
            iran_ratio = sum(1 for s in in_window if s.get("region")=="iranian")/len(in_window)
            explanation = f"{canonical} is {lifecycle} based on {evidence_count} signals from {supporting_sources} independent sources in last {window_days} days, with recency R={comps['R']:.2f} (half-life {cfg.get('half_life_days')}d), growth {growth_rate:+.1%}, cross-source {comps['C']:.2f}, seasonal {comps['S']:.2f}. Iranian evidence {iran_ratio:.0%} (I={comps['I']:.2f})."
        results.append({
            "canonical_name": canonical,
            "category": in_window[0].get("category","unknown"),
            "global_score": comps["G"],
            "iran_relevance_score": comps["I"],
            "recency_score": comps["R"],
            "growth_score": comps["Gw"],
            "cross_source_score": comps["C"],
            "seasonal_relevance": comps["S"],
            "current_score": score,
            "components": comps,
            "lifecycle_state": lifecycle,
            "first_seen_utc": first_seen,
            "last_seen_utc": last_seen,
            "evidence_count": evidence_count,
            "supporting_sources": supporting_sources,
            "is_actionable": is_actionable,
            "explanation": explanation,
            "growth_rate": growth_rate,
            "persistence": persistence,
        })
    return results

def _gregorian_season(month: int) -> str:
    if month in [3,4,5]:
        return "spring"
    if month in [6,7,8]:
        return "summer"
    if month in [9,10,11]:
        return "autumn"
    return "winter"
