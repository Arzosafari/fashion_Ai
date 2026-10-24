"""Semantic clustering + cross-source concept merging.

Design (preserved from the Global Fashion Trend module):

* Sentence-Transformers cosine similarity is the primary signal
  (``paraphrase-multilingual-MiniLM-L12-v2`` by default, configurable in
  ``config/taxonomy.yaml``).
* When the optional embedding stack (``sentence-transformers`` + ``torch``) is
  not installed, a deterministic hashed n-gram embedding is used so the
  pipeline keeps working offline — never silently degrading to "merge all".
* Similarity is enriched with structured attributes (category, garment, color,
  season, material, styling) and a synonym-aware token overlap guard.  Two
  concepts with *different* categories are never merged, which prevents
  ``red tailoring`` (styling) from absorbing ``red handbag`` (accessory).
* The threshold is configurable (default 0.58) via
  ``TREND_SIMILARITY_THRESHOLD``.
"""

from __future__ import annotations

import logging
import math
import os
from hashlib import blake2b

from trend_system.normalization.synonym_mapper import (
    expand_tokens,
    get_embedding_model_name,
    get_similarity_threshold,
    tokenize,
)

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 256
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOAD_FAILED = False

# Attribute-like tokens (colors, materials, seasons, generic adjectives).  A
# containment match only merges concepts when the shared tokens include at
# least one *core* noun — this prevents "oversized style" (only a modifier)
# from being absorbed by "statement belts", while still merging "handbag" with
# "red handbag" or "floral brooches" with "oversized floral brooches".
_MODIFIER_TOKENS = {
    "statement", "bold", "oversized", "dramatic", "elevated", "new", "latest",
    "red", "scarlet", "crimson", "cherry", "black", "white", "blue", "green",
    "pink", "beige", "brown", "gold", "golden", "silver", "camel", "ecru",
    "linen", "flax", "wool", "woolen", "tweed", "denim", "silk", "leather",
    "cotton", "suede", "modal", "chiffon", "jacquard", "corduroy",
    "spring", "summer", "autumn", "fall", "winter", "resort", "pre", "ss", "aw", "fw",
    "print", "pattern", "floral", "animal",
}


def _hash_embedding(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Deterministic feature-hashing embedding (offline fallback)."""
    vec = [0.0] * dim
    tokens = tokenize(text)
    features: list[str] = list(tokens)
    # character trigrams add tolerance for spelling variants
    compact = " ".join(tokens)
    for i in range(max(0, len(compact) - 2)):
        features.append(compact[i:i + 3])
    for feature in features:
        digest = blake2b(feature.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a, b) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _load_sentence_transformer():
    """Lazily load the Sentence-Transformers model; return None on failure."""
    global _MODEL_LOAD_FAILED
    if os.getenv("TREND_EMBEDDINGS_DISABLED") == "1":
        return None
    if _MODEL_LOAD_FAILED:
        return None
    model_name = get_embedding_model_name()
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    try:  # optional heavy dependency
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = model
        logger.info("Loaded Sentence-Transformers model %s", model_name)
        return model
    except Exception as exc:  # pragma: no cover - depends on optional install
        _MODEL_LOAD_FAILED = True
        logger.info(
            "Sentence-Transformers unavailable (%s); using deterministic hash embeddings",
            exc,
        )
        return None


class SemanticClusterer:
    """Greedy agglomerative clustering of fashion concepts."""

    def __init__(
        self,
        threshold: float | None = None,
        embedding_model: str | None = None,
        use_embeddings: bool | None = None,
    ):
        self.threshold = (
            float(threshold) if threshold is not None else get_similarity_threshold()
        )
        self.embedding_model_name = embedding_model or get_embedding_model_name()
        self.use_embeddings = (
            use_embeddings
            if use_embeddings is not None
            else os.getenv("TREND_EMBEDDINGS_DISABLED") != "1"
        )

    # ------------------------------------------------------------------ items
    @staticmethod
    def _item_tokens(item: dict) -> set[str]:
        canonical = item.get("canonical") or item.get("name") or ""
        parts: list[str] = [canonical]
        attributes = item.get("attributes") or {}
        if isinstance(attributes, dict):
            for value in attributes.values():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (list, tuple, set)):
                    parts.extend(str(v) for v in value)
        tokens: list[str] = []
        for part in parts:
            tokens.extend(tokenize(part))
        return expand_tokens(tokens)

    def _item_text(self, item: dict) -> str:
        canonical = item.get("canonical") or item.get("name") or ""
        attributes = item.get("attributes") or {}
        attr_text = " ".join(
            f"{k} {v}" for k, v in attributes.items() if isinstance(v, (str, int, float))
        )
        return f"{canonical.replace('_', ' ')} {attr_text}".strip()

    def _embedding_similarity(self, text_a: str, text_b: str) -> tuple[float, bool]:
        """Return ``(similarity, is_true_sentence_embedding)``.

        Hash-embedding similarity is only a degraded fallback and is noisier
        than a trained transformer, so callers require a much higher score
        before trusting it for a merge.
        """
        if not self.use_embeddings:
            return 0.0, False
        model = _load_sentence_transformer()
        try:
            if model is not None:
                vectors = model.encode(
                    [text_a, text_b], normalize_embeddings=True, show_progress_bar=False
                )
                return (
                    float(sum(float(x) * float(y) for x, y in zip(vectors[0], vectors[1]))),
                    True,
                )
            return _cosine(_hash_embedding(text_a), _hash_embedding(text_b)), False
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("embedding similarity failed: %s", exc)
            return 0.0, False

    # ------------------------------------------------------------- similarity
    def similarity(self, item_a: dict, item_b: dict) -> float:
        cat_a = item_a.get("category")
        cat_b = item_b.get("category")
        if cat_a and cat_b and cat_a != cat_b:
            # Category guard: never merge a styling trend with an accessory.
            return 0.0

        tokens_a = self._item_tokens(item_a)
        tokens_b = self._item_tokens(item_b)
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        jaccard = len(intersection) / len(union) if union else 0.0
        containment = (
            len(intersection) / min(len(tokens_a), len(tokens_b))
            if tokens_a and tokens_b
            else 0.0
        )
        # Containment is only trusted when the shared tokens contain a core
        # noun (see _MODIFIER_TOKENS).
        core_intersection = {
            token for token in intersection if token not in _MODIFIER_TOKENS
        }
        containment = containment if core_intersection else 0.0
        lexical = max(jaccard, containment)

        embedding, is_true_embedding = self._embedding_similarity(
            self._item_text(item_a), self._item_text(item_b)
        )
        # Trained embeddings are trusted at the configured threshold; the
        # deterministic hash fallback needs 0.90+ to avoid noisy merges.
        min_embedding = self.threshold if is_true_embedding else 0.90
        if embedding < min_embedding:
            embedding = 0.0
        # A pure embedding match without any shared token is only trusted for
        # already very similar strings, to avoid false merges between concepts
        # that merely co-occur in the same article.
        if not intersection and embedding < min(0.95, self.threshold + 0.2):
            return 0.0
        return max(lexical, embedding)

    def _similarity_to_cluster(self, item: dict, cluster: dict) -> float:
        best = 0.0
        for member in cluster["items"]:
            best = max(best, self.similarity(item, member))
            if best >= 1.0:
                break
        return best

    # ---------------------------------------------------------------- cluster
    def cluster(self, items: list[dict]) -> list[list[dict]]:
        clusters: list[dict] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            best_cluster = None
            best_score = 0.0
            for cluster in clusters:
                score = self._similarity_to_cluster(item, cluster)
                if score >= self.threshold and score > best_score:
                    best_cluster = cluster
                    best_score = score
            if best_cluster is not None:
                best_cluster["items"].append(item)
            else:
                clusters.append({"items": [item]})
        return [c["items"] for c in clusters]


def semantic_dedup_signals(
    signals_by_concept: dict[str, list[dict]],
    threshold: float | None = None,
    clusterer: SemanticClusterer | None = None,
) -> dict[str, list[dict]]:
    """Merge near-duplicate concepts coming from different sources.

    ``signals_by_concept`` maps canonical concept → signal dicts.  The returned
    mapping is keyed by the representative canonical name (the concept with the
    most evidence), and keeps every original signal so provenance is preserved.
    """
    if not signals_by_concept:
        return {}

    clusterer = clusterer or SemanticClusterer(threshold=threshold)
    items: list[dict] = []
    for canonical, signals in signals_by_concept.items():
        signals = signals or []
        if not signals:
            continue
        category = next((s.get("category") for s in signals if s.get("category")), None)
        attributes: dict[str, object] = {}
        for signal in signals:
            attrs = signal.get("extracted_attributes") or signal.get("attributes")
            if isinstance(attrs, dict):
                for key, value in attrs.items():
                    if key not in attributes and value not in (None, "", []):
                        attributes[key] = value
        items.append(
            {
                "canonical": canonical,
                "category": category,
                "attributes": attributes,
                "_count": len(signals),
            }
        )

    clusters = clusterer.cluster([{k: v for k, v in it.items() if k != "_count"} for it in items])
    counts = {it["canonical"]: it["_count"] for it in items}

    merged: dict[str, list[dict]] = {}
    for cluster in clusters:
        canonicals = [it["canonical"] for it in cluster]
        representative = max(canonicals, key=lambda c: (counts.get(c, 0), -canonicals.index(c)))
        bucket: list[dict] = []
        for canonical in canonicals:
            bucket.extend(signals_by_concept.get(canonical, []))
        merged[representative] = bucket
    return merged
