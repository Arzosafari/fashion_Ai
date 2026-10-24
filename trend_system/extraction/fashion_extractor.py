from __future__ import annotations
import re
from typing import Dict

# Simple gazetteer-based extraction + regex

# Build gazetteer from taxonomy
def _build_gazetteer():
    from trend_system.config import get_taxonomy_config
    cfg = get_taxonomy_config()
    gaz = {}
    for ent in cfg.get("entities", []):
        canon = ent["canonical"]
        cat = ent["category"]
        for alias in ent.get("aliases", []):
            gaz[alias.lower()] = (canon, cat)
    return gaz

_GAZ = None

def get_gazetteer():
    global _GAZ
    if _GAZ is None:
        _GAZ = _build_gazetteer()
    return _GAZ

def _normalize_text(s: str) -> str:
    # Normalize hyphens, zero-width, etc.
    s = s.replace("-", " ").replace("–", " ").replace("—", " ")
    s = re.sub(r"\s+", " ", s)
    return s

def extract_fashion_attributes(text: str, title: str | None = None, language: str = "en") -> Dict:
    combined_raw = f"{title or ''} {text}".lower()
    combined = _normalize_text(combined_raw)
    gaz = get_gazetteer()
    found: Dict[str, list] = {"garments":[],"colors":[],"patterns":[],"styles":[],"materials":[],"silhouettes":[],"outfit_combinations":[],"trend_candidates":[]}
    cat_map = {
        "garment":"garments",
        "color":"colors",
        "pattern":"patterns",
        "style":"styles",
        "material":"materials",
        "silhouette":"silhouettes",
        "outfit_combination":"outfit_combinations",
        "accessory":"garments",
        "aesthetic":"styles",
        "styling":"styles",
        "outerwear":"garments",
        "footwear":"garments",
        "occasion":"styles",
        "macro_trend":"styles",
        "micro_trend":"styles",
        "designer":"garments",
    }
    # Sort aliases by length desc to match longest first
    for alias, (canon, cat) in sorted(gaz.items(), key=lambda x: len(x[0]), reverse=True):
        if not alias:
            continue
        alias_norm = _normalize_text(alias.lower())
        # For Persian aliases, simple substring; for English, word boundary
        if re.search(r"[\u0600-\u06FF]", alias_norm):
            if alias_norm in combined:
                bucket = cat_map.get(cat, "styles")
                if canon not in found[bucket]:
                    found[bucket].append(canon)
        else:
            # English with word boundary
            if re.search(r"\b" + re.escape(alias_norm) + r"\b", combined):
                bucket = cat_map.get(cat, "styles")
                if canon not in found[bucket]:
                    found[bucket].append(canon)
    # trend_candidates: all found
    all_cands = []
    for k in ["garments","colors","patterns","styles","materials","silhouettes","outfit_combinations"]:
        all_cands.extend(found[k])
    found["trend_candidates"] = all_cands
    # confidence: heuristic based on count
    return found

def extraction_confidence(found: dict) -> float:
    n = len(found.get("trend_candidates", []))
    if n >= 4:
        return 0.9
    if n >= 2:
        return 0.75
    if n == 1:
        return 0.6
    return 0.3
