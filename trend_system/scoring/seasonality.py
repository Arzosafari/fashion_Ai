"""Seasonal relevance for global fashion trends."""

from __future__ import annotations

import re

from trend_system.config import get_scoring_config, get_seasonal_config

_DEFAULT_RANGE = (0.5, 1.2)


def _clamp(value: float, bounds) -> float:
    low, high = bounds
    return max(float(low), min(float(high), float(value)))


def _season_keys(season: str | None) -> list[str]:
    """Map a season label to lookup keys.

    ``"Spring/Summer 2026"`` → ``["Spring/Summer 2026", "spring", "summer"]`` so
    that both the normalized fashion season and the plain seasonal affinity can
    be used.
    """
    if not season:
        return []
    season = str(season)
    keys = [season, season.lower()]
    parts = re.findall(r"[A-Za-z]+", season)
    keys.extend(p.lower() for p in parts)
    if "spring" in [k.lower() for k in keys] and "summer" in [k.lower() for k in keys]:
        keys.append("Spring/Summer")
    if "fall" in [k.lower() for k in keys] and "winter" in [k.lower() for k in keys]:
        keys.append("Fall/Winter")
    seen = set()
    unique = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def get_season_affinity(canonical: str, season: str | None) -> float:
    """Seasonal affinity multiplier for a concept (0.5 = off-season, 1.2 = peak)."""
    cfg = get_scoring_config()
    bounds = (
        (cfg.get("seasonal") or {}).get("boost_range")
        or _DEFAULT_RANGE
    )
    try:
        seasonal_cfg = get_seasonal_config() or {}
    except Exception:
        seasonal_cfg = {}
    affinities = seasonal_cfg.get("affinities") or {}
    entry = affinities.get(canonical)
    if not isinstance(entry, dict) or not entry:
        default = seasonal_cfg.get("default_affinity") or {}
        for key in _season_keys(season):
            if key in default:
                return _clamp(default[key], bounds)
        return 1.0

    lowered = {str(k).lower(): v for k, v in entry.items()}
    for key in _season_keys(season):
        if key in entry:
            return _clamp(entry[key], bounds)
        if key.lower() in lowered:
            return _clamp(lowered[key.lower()], bounds)
    return 1.0


def seasonal_relevance(canonical: str, season: str | None, cfg: dict | None = None) -> float:
    """Alias kept for callers that pass an explicit scoring config."""
    return get_season_affinity(canonical, season)
