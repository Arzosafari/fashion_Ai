"""Trend lifecycle classification.

Thresholds come from ``config/scoring.yaml:lifecycle`` so behaviour can be tuned
without code changes.  The states are: ``emerging``, ``rising``,
``established``, ``declining``, ``inactive`` and a neutral ``stable`` fallback
(the value used by the historical snapshots shipped with this repository).
"""

from __future__ import annotations

from trend_system.config import get_scoring_config


def determine_lifecycle(
    evidence_count: int,
    supporting_sources: int,
    score: float,
    growth_rate: float,
    persistence: float,
    age_first_days: float,
    age_last_days: float,
    cfg: dict | None = None,
) -> str:
    cfg = cfg or get_scoring_config()
    lifecycle_cfg = cfg.get("lifecycle") or {}

    inactive = lifecycle_cfg.get("inactive") or {}
    if age_last_days is not None and age_last_days > float(inactive.get("last_seen_gt_days", 60)):
        return "inactive"
    if score is not None and score < float(inactive.get("score_lt", 0.15)):
        return "inactive"

    declining = lifecycle_cfg.get("declining") or {}
    if growth_rate is not None and growth_rate < float(declining.get("growth_lt", -0.10)):
        return "declining"

    emerging = lifecycle_cfg.get("emerging") or {}
    if (
        evidence_count >= int(emerging.get("min_evidence", 3))
        and age_first_days is not None
        and age_first_days <= float(emerging.get("max_age_days", 14))
        and growth_rate is not None
        and growth_rate > float(emerging.get("growth_gt", 0.25))
        and supporting_sources >= int(emerging.get("sources_ge", 2))
    ):
        return "emerging"

    rising = lifecycle_cfg.get("rising") or {}
    if (
        growth_rate is not None
        and growth_rate > float(rising.get("growth_gt", 0.10))
        and persistence is not None
        and persistence > float(rising.get("persistence_gt", 0.5))
    ):
        return "rising"

    established = lifecycle_cfg.get("established") or {}
    if (
        score is not None
        and score > float(established.get("score_gt", 0.6))
        and persistence is not None
        and persistence > float(established.get("persistence_gt", 0.7))
        and growth_rate is not None
        and abs(growth_rate) < float(established.get("abs_growth_lt", 0.10))
        and evidence_count > int(established.get("evidence_gt", 10))
    ):
        return "established"

    return "stable"
