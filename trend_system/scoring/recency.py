"""Freshness / recency decay used by trend scoring."""

from __future__ import annotations

import math
from datetime import datetime, timezone


def age_days(timestamp: datetime | None, now: datetime | None = None) -> float:
    """Age of ``timestamp`` in days (never negative)."""
    if timestamp is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    ts = timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def recency_weight(
    age_in_days: float,
    half_life_days: float = 30.0,
    decay_type: str = "exponential",
) -> float:
    """Freshness weight in ``(0, 1]``.

    * ``exponential`` (default): ``2 ** (-age / half_life)`` — age 30 with a
      30-day half-life → 0.5, age 60 → 0.25.
    * ``power_law``: ``1 / (1 + age / half_life)`` — same half point, heavier
      tail, useful for slow-moving macro trends.
    """
    try:
        age = max(0.0, float(age_in_days))
    except (TypeError, ValueError):
        age = 0.0
    try:
        half_life = float(half_life_days)
    except (TypeError, ValueError):
        half_life = 30.0
    if half_life <= 0:
        return 1.0
    decay = (decay_type or "exponential").lower()
    if decay.startswith("power"):
        return 1.0 / (1.0 + age / half_life)
    return math.pow(2.0, -age / half_life)


def timestamp_recency_weight(
    timestamp: datetime,
    now: datetime,
    half_life_days: float = 30.0,
    decay_type: str = "exponential",
) -> float:
    return recency_weight(age_days(timestamp, now), half_life_days, decay_type)
