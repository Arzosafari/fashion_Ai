from __future__ import annotations
import re

# Global season normalization per spec
_SEASON_MAP = {
    "SS26": "Spring/Summer 2026",
    "SS 26": "Spring/Summer 2026",
    "SS2026": "Spring/Summer 2026",
    "S/S 2026": "Spring/Summer 2026",
    "S/S26": "Spring/Summer 2026",
    "AW26": "Fall/Winter 2026",
    "AW 2026": "Fall/Winter 2026",
    "AW2026": "Fall/Winter 2026",
    "FW26": "Fall/Winter 2026",
    "FW 26": "Fall/Winter 2026",
    "FW2026": "Fall/Winter 2026",
    "F/W 2026": "Fall/Winter 2026",
    "SS25": "Spring/Summer 2025",
    "AW25": "Fall/Winter 2025",
    "RESORT 2026": "Resort 2026",
    "RESORT26": "Resort 2026",
    "PRE-FALL 2026": "Pre-Fall 2026",
}

_FASHION_WEEKS = ["NY", "London", "Milan", "Paris", "Copenhagen", "New York"]
_FASHION_WEEK_PATTERN = re.compile(r"\b(NY|New York|London|Milan|Paris|Copenhagen)\s+Fashion\s+Week\b", re.IGNORECASE)
_SEASON_PATTERN = re.compile(r"\b(SS|AW|FW|S/S|F/W)\s*[- ]?\s*(\d{2,4})\b", re.IGNORECASE)
_SEASON_FULL_PATTERN = re.compile(r"\b(Spring/Summer|Fall/Winter|Resort|Pre-Fall)\s*(\d{4})\b", re.IGNORECASE)

def normalize_season_tag(text: str, default: str | None = None) -> str:
    """Normalize season tags like SS26 -> Spring/Summer 2026, with fallback to default."""
    if not text:
        return default or "unknown"
    upper = text.upper()
    # Direct map check
    for k, v in _SEASON_MAP.items():
        if k.upper() in upper:
            return v
    # Regex SS26
    m = _SEASON_PATTERN.search(text)
    if m:
        prefix = m.group(1).upper().replace("/", "").replace("-", "")
        year_raw = m.group(2)
        # Normalize year to 4 digits
        if len(year_raw) == 2:
            year = f"20{year_raw}"
        else:
            year = year_raw
        if prefix in ("SS", "S", "S S"):
            return f"Spring/Summer {year}"
        if prefix in ("AW", "FW", "F", "F W"):
            return f"Fall/Winter {year}"
    m2 = _SEASON_FULL_PATTERN.search(text)
    if m2:
        season = m2.group(1)
        year = m2.group(2)
        # Title case
        season = season.title().replace("Fall/Winter", "Fall/Winter").replace("Spring/Summer", "Spring/Summer")
        return f"{season} {year}"
    return default or "unknown"

def extract_fashion_weeks(text: str) -> list[str]:
    """Extract fashion week mentions (NY, London, Milan, Paris, Copenhagen) extensible."""
    if not text:
        return []
    found = set()
    for m in _FASHION_WEEK_PATTERN.finditer(text):
        wk = m.group(1)
        # Normalize NY/New York
        if wk.lower() in ("ny", "new york"):
            found.add("NY")
        else:
            found.add(wk.title())
    return sorted(found)

def extract_season_context(text: str) -> dict:
    """Return dict with normalized season and fashion weeks for evidence enhancement."""
    return {
        "normalized_season": normalize_season_tag(text),
        "fashion_weeks": extract_fashion_weeks(text),
    }
