"""Fashion taxonomy and canonical-name normalization.

The taxonomy itself lives in ``config/taxonomy.yaml`` so it can be extended
without code changes.  This module only provides lookups and text
normalization, keeping the data-driven design of the original module.
"""

from __future__ import annotations

import re
from functools import lru_cache

from trend_system.config import get_taxonomy_config

_ZWNJ = "\u200c"
_HYPHENS = "-–—‐‑_"
_SPACE_RE = re.compile(r"\s+")


def normalize_term(value: str | None) -> str:
    """Lowercase, strip hyphens/zero-width joiners and collapse whitespace."""
    if not value:
        return ""
    text = str(value).lower()
    for ch in _HYPHENS:
        text = text.replace(ch, " ")
    text = text.replace(_ZWNJ, " ")
    text = text.replace("&", " and ")
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _singularize(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and token[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


@lru_cache(maxsize=1)
def get_taxonomy_entities() -> tuple[dict, ...]:
    """Return the configured taxonomy entities as an immutable tuple."""
    cfg = get_taxonomy_config() or {}
    entities = []
    for ent in cfg.get("entities", []):
        canonical = ent.get("canonical")
        if not canonical:
            continue
        entities.append(
            {
                "canonical": canonical,
                "category": ent.get("category", "unknown"),
                "aliases": list(ent.get("aliases", []) or []),
                "global_relevance": ent.get("global_relevance"),
                "iran_compatibility": ent.get("iran_compatibility"),
                "ideal_temp_range": ent.get("ideal_temp_range"),
            }
        )
    return tuple(entities)


@lru_cache(maxsize=1)
def get_taxonomy_map() -> dict[str, tuple[str, str]]:
    """Alias (normalized) → ``(canonical, category)`` lookup table."""
    mapping: dict[str, tuple[str, str]] = {}
    for ent in get_taxonomy_entities():
        canonical = ent["canonical"]
        category = ent["category"]
        mapping[normalize_term(canonical)] = (canonical, category)
        for alias in ent["aliases"]:
            key = normalize_term(alias)
            if key and key not in mapping:
                mapping[key] = (canonical, category)
    return mapping


@lru_cache(maxsize=1)
def get_category_map() -> dict[str, str]:
    return {ent["canonical"]: ent["category"] for ent in get_taxonomy_entities()}


def get_entity(canonical: str) -> dict | None:
    for ent in get_taxonomy_entities():
        if ent["canonical"] == canonical:
            return dict(ent)
    return None


def get_category(canonical: str | None) -> str | None:
    if not canonical:
        return None
    return get_category_map().get(canonical)


def lookup_canonical(term: str, language: str | None = None) -> tuple[str | None, str | None]:
    """Resolve a free-text fashion term to ``(canonical_name, category)``.

    Matching order: exact alias → singularized alias → unique token-subset
    match.  Returns ``(None, None)`` when the term is unknown so callers can
    decide whether to keep the raw term or drop it.
    """
    norm = normalize_term(term)
    if not norm:
        return (None, None)

    mapping = get_taxonomy_map()
    if norm in mapping:
        return mapping[norm]

    # Try singular/plural variants token-by-token ("handbags" → "handbag").
    tokens = [_singularize(t) for t in norm.split(" ")]
    singular = " ".join(tokens)
    if singular in mapping:
        return mapping[singular]

    # Try removing common trend adjectives that are not part of the entity.
    for prefix in ("oversized ", "bold ", "dramatic ", "sculptural ", "statement "):
        if norm.startswith(prefix) and norm[len(prefix):] in mapping:
            return mapping[norm[len(prefix):]]

    # Unique token-subset match, e.g. "wide leg trousers in linen" → linen.
    hits: dict[tuple[str, str], int] = {}
    norm_tokens = set(tokens)
    for alias, value in mapping.items():
        alias_tokens = set(alias.split(" "))
        if alias_tokens and alias_tokens.issubset(norm_tokens):
            hits[value] = hits.get(value, 0) + 1
    if len(hits) == 1:
        return next(iter(hits))
    return (None, None)


def reload_taxonomy() -> None:
    """Clear caches (used by scripts after editing ``taxonomy.yaml``)."""
    get_taxonomy_entities.cache_clear()
    get_taxonomy_map.cache_clear()
    get_category_map.cache_clear()
