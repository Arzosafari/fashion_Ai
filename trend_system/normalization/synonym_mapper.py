"""Synonym-aware helpers for fashion concept normalization.

Two concepts that differ only by a stylistic synonym ("scarlet tailoring" vs
"red tailoring") should be treated as the same trend, while sharing a single
attribute ("red tailoring" vs "red handbag") must not merge different garment
categories.  The synonym groups below are deliberately small and explicit.
"""

from __future__ import annotations

import os
import re

from trend_system.config import get_scoring_config, get_taxonomy_config

DEFAULT_SIMILARITY_THRESHOLD = 0.58

# Groups are expanded into a canonical token per group.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("red", "scarlet", "crimson", "cherry"),
    ("tailoring", "tailored", "tailor", "suiting", "suit", "suits", "suitings"),
    ("handbag", "handbags", "bag", "bags", "purse", "purses"),
    ("trousers", "trouser", "pants", "pant", "slacks"),
    ("wide", "baggy", "palazzo", "loose"),
    ("coat", "overcoat", "trench", "trenchcoat"),
    ("jacket", "bomber", "blouson"),
    ("floral", "flower", "flowers", "florals"),
    ("print", "prints", "pattern", "patterns"),
    ("statement", "bold", "oversized", "dramatic"),
    ("shoe", "shoes", "footwear"),
    ("boot", "boots"),
    ("dress", "dresses", "gown", "gowns"),
    ("sweater", "jumper", "pullover", "knitwear"),
    ("linen", "flax"),
    ("wool", "woollen", "woolen", "tweed"),
    ("denim", "jeans", "jean"),
    ("spring", "ss"),
    ("fall", "autumn", "aw", "fw"),
)

_SYNONYM_MAP: dict[str, str] = {}
for group in _SYNONYM_GROUPS:
    canonical = group[0]
    for token in group:
        _SYNONYM_MAP[token] = canonical

_TOKEN_RE = re.compile(r"[a-z0-9\u0600-\u06FF]+")

# Tokens that carry no discriminating meaning for clustering.
_STOPWORDS = {
    "the", "a", "an", "and", "of", "with", "in", "on", "for", "to", "its",
    "trend", "trends", "trending", "style", "styled", "look", "looks",
    "fashion", "fashionable", "season", "collection", "new", "latest",
}


def get_similarity_threshold() -> float:
    """Cosine/Jaccard threshold for semantic clustering.

    Resolution order: ``TREND_SIMILARITY_THRESHOLD`` env var → ``scoring.yaml``
    → ``taxonomy.yaml:normalization.similarity_threshold`` → 0.58.
    Read on every call so operators can tune without restarting long jobs.
    """
    env_value = os.getenv("TREND_SIMILARITY_THRESHOLD")
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            pass
    try:
        cfg = get_scoring_config()
        if cfg.get("similarity_threshold") is not None:
            return float(cfg["similarity_threshold"])
    except Exception:
        pass
    try:
        tax = get_taxonomy_config() or {}
        value = (tax.get("normalization") or {}).get("similarity_threshold")
        if value is not None:
            return float(value)
    except Exception:
        pass
    return DEFAULT_SIMILARITY_THRESHOLD


def get_embedding_model_name() -> str:
    try:
        tax = get_taxonomy_config() or {}
        return (tax.get("normalization") or {}).get(
            "embedding_model", "paraphrase-multilingual-MiniLM-L12-v2"
        )
    except Exception:
        return "paraphrase-multilingual-MiniLM-L12-v2"


def tokenize(value: str | None) -> list[str]:
    if not value:
        return []
    raw = str(value).lower().replace("-", " ").replace("_", " ")
    tokens = []
    for token in _TOKEN_RE.findall(raw):
        if token in _STOPWORDS:
            continue
        tokens.append(_SYNONYM_MAP.get(token, token))
    return tokens


def expand_tokens(tokens) -> set[str]:
    return {_SYNONYM_MAP.get(t, t) for t in tokens if t and t not in _STOPWORDS}
