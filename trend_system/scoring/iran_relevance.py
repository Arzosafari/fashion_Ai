"""Iran relevance gate.

The active pipeline is **global**: ``config/scoring.yaml`` sets
``trend_scope: global`` and ``iran_relevance.enabled: false``, in which case the
gate is neutral (``I = 1.0``) and never penalises global-only evidence.

The legacy Iranian formula is kept for backward compatibility with historical
rows (``trend_scope = iranian``) and can be re-enabled via configuration; it is
never activated by the global collector.
"""

from __future__ import annotations

from trend_system.config import get_scoring_config


def is_iran_gate_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or get_scoring_config()
    if cfg.get("trend_scope") == "global":
        return False
    iran_cfg = cfg.get("iran_relevance") or {}
    return bool(iran_cfg.get("enabled", False))


def compute_iran_relevance(
    iran_source_ratio: float,
    fa_ratio: float,
    canonical: str | None = None,
    market_proxy: float | None = None,
    cfg: dict | None = None,
) -> float:
    """Return the Iran relevance score ``I`` in ``[0, 1]``.

    For the global pipeline this is always ``1.0`` (neutral gate).  The legacy
    formula is a weighted blend of Iranian evidence ratio, Persian-language
    ratio and (only if explicitly enabled) a market proxy.  No market signal is
    ever fabricated when the proxy is missing.
    """
    cfg = cfg or get_scoring_config()
    if not is_iran_gate_enabled(cfg):
        return 1.0

    iran_cfg = cfg.get("iran_relevance") or {}
    w_source = float(iran_cfg.get("w_iran_source", 0.45))
    w_lang = float(iran_cfg.get("w_lang", 0.30))
    # "w_norms" (social-norms compatibility) is reserved in the config; no
    # norms signal is available to this function, so it is not applied.
    _w_norms = float(iran_cfg.get("w_norms", 0.25))  # noqa: F841 - reserved
    w_market = float(iran_cfg.get("w_market", 0.0))
    market_enabled = bool(iran_cfg.get("market_enabled", False))

    source_component = max(0.0, min(1.0, float(iran_source_ratio or 0.0)))
    lang_component = max(0.0, min(1.0, float(fa_ratio or 0.0)))
    base = 0.25 + w_source * source_component + w_lang * lang_component

    if market_enabled and market_proxy is not None and w_market > 0:
        base += w_market * max(0.0, min(1.0, float(market_proxy)))

    # Keep the legacy floor/ceiling used by historical reports.
    return max(0.2, min(1.0, base))
