"""
Fashion Request Understanding & Feature Extractor
Extracts structured fashion features (intents, occasions, formality, locations,
times, styles, garments, colors, fits, functional requirements, constraints, negations)
from natural English speech or typed text.
"""

import os
import re
import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

from .lexicon import (
    FASHION_CATEGORIES,
    FASHION_MATERIALS,
    FASHION_STYLES,
    FASHION_PATTERNS,
    FASHION_COLORS,
    FASHION_BRANDS,
    correct_fashion_text
)
from .models import (
    FashionRequestOutput,
    IntentModel,
    OccasionModel,
    LocationModel,
    TimeModel,
    StylePreferenceItem,
    GarmentPreferencesModel,
    ColorPreferencesModel
)

def _default_reference_date() -> datetime.date:
    env_date = os.environ.get("FASHION_REFERENCE_DATE")
    if env_date:
        try:
            return datetime.date.fromisoformat(env_date.strip())
        except ValueError:
            pass
    return datetime.date.today()


# Default reference date helper (uses current date or FASHION_REFERENCE_DATE override)
REFERENCE_DATE = _default_reference_date()

WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "a": 1, "an": 1
}


def parse_spoken_number(text: str) -> Optional[float]:
    """Parses spoken word numbers ('two hundred', 'one hundred fifty') or digit strings ('200')."""
    if not text:
        return None
    text = text.strip().lower()
    if re.match(r"^\d+(\.\d+)?$", text):
        return float(text)

    tokens = text.replace("-", " ").replace(" and ", " ").split()
    total = 0
    current = 0
    found_any = False

    for tok in tokens:
        if tok in WORD_NUMBERS:
            current += WORD_NUMBERS[tok]
            found_any = True
        elif tok == "hundred":
            current = (current if current else 1) * 100
            found_any = True
        elif tok == "thousand":
            total += (current if current else 1) * 1000
            current = 0
            found_any = True

    if not found_any:
        return None
    return float(total + current)


# Known Occasions and Formality Mappings
OCCASION_MAPPINGS = {
    "job interview": {"val": "job interview", "formality": "formal"},
    "interview": {"val": "job interview", "formality": "formal"},
    "wedding": {"val": "wedding", "formality": "formal"},
    "summer wedding": {"val": "summer wedding", "formality": "formal"},
    "graduation ceremony": {"val": "graduation", "formality": "semi-formal"},
    "graduation": {"val": "graduation", "formality": "semi-formal"},
    "formal dinner": {"val": "formal dinner", "formality": "formal"},
    "dinner party": {"val": "dinner party", "formality": "semi-formal"},
    "dinner": {"val": "dinner", "formality": "semi-formal"},
    "cocktail party": {"val": "cocktail party", "formality": "formal"},
    "party": {"val": "party", "formality": "casual"},
    "date night": {"val": "date night", "formality": "semi-formal"},
    "first date": {"val": "first date", "formality": "semi-formal"},
    "business meeting": {"val": "business meeting", "formality": "formal"},
    "office": {"val": "work / office", "formality": "business_casual"},
    "work": {"val": "work / office", "formality": "business_casual"},
    "conference": {"val": "conference", "formality": "business_casual"},
    "outdoor event": {"val": "outdoor event", "formality": "casual"},
    "walking around": {"val": "casual walking", "formality": "casual"},
    "sightseeing": {"val": "sightseeing", "formality": "casual"},
    "travel": {"val": "travel", "formality": "casual"},
    "vacation": {"val": "vacation", "formality": "casual"},
    "beach": {"val": "beach", "formality": "casual"},
    "gym": {"val": "gym / workout", "formality": "sportswear"},
    "workout": {"val": "gym / workout", "formality": "sportswear"},
    "funeral": {"val": "funeral", "formality": "formal"},
    "gala": {"val": "gala", "formality": "black_tie"},
    "prom": {"val": "prom", "formality": "formal"},
    "brunch": {"val": "brunch", "formality": "casual"}
}

# Formality Keywords
FORMALITY_KEYWORDS = {
    r"\bblack\s+tie\b": "black_tie",
    r"\bformal\b": "formal",
    r"\bsemi[-\s]?formal\b": "semi-formal",
    r"\bbusiness\s+casual\b": "business_casual",
    r"\bsmart\s+casual\b": "business_casual",
    r"\bcasual\b": "casual",
    r"\bsporty|sportswear|athletic\b": "sportswear"
}

# Location Keywords (Cities & Major Metropolitan Regions — sorted longest-first during matching)
LOCATION_KEYWORDS = sorted([
    "New York", "Paris", "London", "Milan", "Tokyo", "Los Angeles", "Rome",
    "Chicago", "San Francisco", "Miami", "Berlin", "Dubai", "Sydney",
    "Toronto", "Venice", "Barcelona", "Amsterdam", "Copenhagen", "Tehran",
    "Shiraz", "Isfahan", "Tabriz", "Mashhad", "Karaj", "Rasht", "Yazd",
    "Kerman", "Ahvaz", "Qom", "Kish", "Baku", "Tbilisi", "Yerevan",
    "Boston", "Dallas", "Fort Worth", "San Antonio", "Plano", "Arlington",
    "Frisco", "Irving", "Austin", "Houston", "Seattle", "Washington",
    "Philadelphia", "Phoenix", "Denver", "Atlanta", "San Diego", "Portland",
    "Las Vegas", "Minneapolis", "Detroit", "Montreal", "Vancouver",
    "Mexico City", "Edinburgh", "Manchester", "Dublin", "Munich", "Frankfurt",
    "Hamburg", "Madrid", "Lisbon", "Brussels", "Vienna", "Zurich", "Geneva",
    "Nice", "Monaco", "Antalya", "Stockholm", "Oslo", "Helsinki", "Reykjavik",
    "Prague", "Warsaw", "Budapest", "Athens", "Istanbul", "Doha", "Riyadh",
    "Cairo", "Kyoto", "Seoul", "Singapore", "Hong Kong", "Bangkok", "Mumbai",
    "Delhi", "Beijing", "Shanghai", "Taipei", "Melbourne", "Auckland",
    "Buenos Aires"
], key=lambda x: -len(x))

# Functional Requirements Keywords
FUNCTIONAL_KEYWORDS = {
    r"\bwarm(th)?\b|\bkeep\s+warm\b|\bcold\s+weather\b": "warmth",
    r"\bcomfortable\b|\bcomfort\b|\beasy\s+to\s+walk\b": "comfort",
    r"\bbreathable\b|\bbreathability\b|\blightweight\b": "breathability",
    r"\bmodest\b|\bmodesty\b": "modesty",
    r"\bmobility\b|\beasy\s+to\s+move\b|\bflexible\b": "mobility",
    r"\bwaterproof\b|\brainy?\b|\braincoat\b|\bumbrella\b": "weather_protection",
    r"\bwindproof\b": "wind_protection",
    r"\bdurable\b|\bdurability\b": "durability"
}

# Fit & Silhouette Keywords
FIT_KEYWORDS = {
    r"\boversized?\b": "oversized",
    r"\btailored\b": "tailored",
    r"\bslim[-\s]?fit\b|\bslim\b": "slim-fit",
    r"\bfitted\b": "fitted",
    r"\bloose\b|\bloose[-\s]?fit\b": "loose",
    r"\brelaxed\b|\brelaxed[-\s]?fit\b": "relaxed",
    r"\blayered\b|\blayering\b": "layered",
    r"\bbaggy\b": "baggy",
    r"\bcropped\b": "cropped",
    r"\bwide[-\s]?leg\b": "wide-leg"
}

# Negation and Exclusion indicator patterns
NEGATION_PATTERNS = [
    r"\b(?:other\s+than|anything\s+other\s+than)\s+([a-zA-Z\s]+?)(?:,|\.|\bfor\b|\bwith\b|\bin\b|$)",
    r"\b(?:rather\s+than|instead\s+of)\s+([a-zA-Z\s]+?)(?:,|\.|\bfor\b|\bwith\b|\bin\b|$)",
    r"\b(?:avoid|avoiding|do\s*n['’]?t\s+want(?:\s+to\s+wear)?|without|except|no|never)\s+([a-zA-Z\s]+?)(?:,|\.|\bfor\b|\bwith\b|\bin\b|$)",
    r"\b(?:not|exclude|excluding)\s+([a-zA-Z\s]+?)(?:,|\.|\bfor\b|\bwith\b|\bin\b|$)"
]


class FashionEntityExtractor:
    """
    Parses natural spoken or typed English fashion requests into structured, validated JSON.
    Handles explicit vs inferred distinction, negations/exclusions, temporal resolution,
    and ambiguity identification.
    """

    def __init__(self, reference_date: Optional[datetime.date] = None):
        self.ref_date = reference_date or _default_reference_date()
        self._build_dictionaries()

    def _build_dictionaries(self):
        # Flatten all garments sorted by length descending
        self.garment_to_category = {}
        for cat, items in FASHION_CATEGORIES.items():
            for item in items:
                self.garment_to_category[item.lower()] = cat

        self.garments_sorted = sorted(self.garment_to_category.keys(), key=lambda x: -len(x))
        self.colors_sorted = sorted(FASHION_COLORS, key=lambda x: -len(x))
        self.styles_sorted = sorted(FASHION_STYLES, key=lambda x: -len(x))
        self.materials_sorted = sorted(FASHION_MATERIALS, key=lambda x: -len(x))
        self.patterns_sorted = sorted(FASHION_PATTERNS, key=lambda x: -len(x))
        self.brands_sorted = sorted(FASHION_BRANDS, key=lambda x: -len(x))

        # Build lowercase vocabulary blocklist so "in <Capitalized Place>" never matches fashion terms
        self._non_location_terms: Set[str] = {
            "small", "medium", "large", "size", "xs", "xxs", "xl", "xxl",
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
            "january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december",
            "spring", "summer", "fall", "autumn", "winter", "morning", "afternoon", "evening",
            "general", "mind", "advance", "addition", "style",
        }
        for group in (
            self.garments_sorted,
            self.colors_sorted,
            self.styles_sorted,
            self.materials_sorted,
            self.patterns_sorted,
            self.brands_sorted,
        ):
            for phrase in group:
                self._non_location_terms.add(phrase.lower())
                for token in phrase.lower().split():
                    self._non_location_terms.add(token)

    def _make_plural_regex(self, word: str) -> str:
        escaped = re.escape(word)
        if word.endswith(("s", "sh", "ch", "x", "z")):
            return rf"\b{escaped}(?:es)?\b"
        elif word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
            stem = re.escape(word[:-1])
            return rf"\b(?:{escaped}|{stem}ies)\b"
        else:
            return rf"\b{escaped}(?:s|es)?\b"

    def extract(
        self, 
        text: str, 
        input_method: str = "text",
        raw_transcript: Optional[str] = None
    ) -> FashionRequestOutput:
        """
        Parses text into a validated FashionRequestOutput object.
        """
        if not text or not text.strip():
            return FashionRequestOutput(
                intent=IntentModel(
                    type="outfit_recommendation",
                    description="Empty request",
                    is_clear=False
                ),
                occasion=OccasionModel(),
                location=LocationModel(),
                time=TimeModel(),
                clarification_needed=True,
                clarification_question="What kind of outfit or clothing are you looking for?",
                raw_input=text,
                clean_input="",
                input_method=input_method
            )

        # 1. Clean & apply phonetic correction
        clean_text, corrections = correct_fashion_text(text)
        lower_text = clean_text.lower()

        # 2. Extract Exclusions / Negations first
        excluded_garments, excluded_colors, general_constraints = self._extract_negations(lower_text)

        # 3. Extract Occasion & Formality
        occasion_model = self._extract_occasion(lower_text)

        # 4. Extract Location
        location_model = self._extract_location(clean_text)

        # 5. Extract Time
        time_model = self._extract_time(lower_text)

        # 6. Extract Style Preferences
        style_preferences = self._extract_styles(lower_text, occasion_model)

        # 7. Extract Preferred Garments (excluding negated items)
        included_garments = self._extract_included_garments(lower_text, excluded_garments)

        # 8. Extract Preferred Colors (excluding negated items)
        preferred_colors = self._extract_preferred_colors(lower_text, excluded_colors)

        # 9. Extract Fit and Silhouette
        fit_preferences = self._extract_fit(lower_text)

        # 10. Extract Functional Requirements
        functional_requirements = self._extract_functional(lower_text)

        # 11. Extract Price & Budget Constraints
        price_constraint = self._extract_price(lower_text)
        if price_constraint:
            general_constraints.append(price_constraint)

        # 12. Determine Intent & Check Ambiguity
        intent_model, clarification_needed, clarification_question = self._determine_intent_and_ambiguity(
            clean_text, occasion_model, included_garments, style_preferences, excluded_garments
        )

        # 13. Determine Missing Context Information
        missing_info = []
        if not occasion_model.value:
            missing_info.append("occasion")
        if not location_model.value:
            missing_info.append("location")
        if not time_model.resolved:
            missing_info.append("time")

        # 14. Calculate confidence
        confidence = self._compute_confidence(occasion_model, included_garments, preferred_colors, style_preferences)

        return FashionRequestOutput(
            intent=intent_model,
            occasion=occasion_model,
            location=location_model,
            time=time_model,
            style_preferences=style_preferences,
            garment_preferences=GarmentPreferencesModel(
                include=included_garments,
                exclude=excluded_garments
            ),
            colors=ColorPreferencesModel(
                preferred=preferred_colors,
                excluded=excluded_colors
            ),
            fit_preferences=fit_preferences,
            functional_requirements=functional_requirements,
            constraints=general_constraints,
            additional_details=[],
            missing_information=missing_info,
            clarification_needed=clarification_needed,
            clarification_question=clarification_question,
            raw_input=raw_transcript or text,
            clean_input=clean_text,
            input_method=input_method,
            confidence_score=confidence
        )

    def _extract_negations(self, text: str) -> Tuple[List[str], List[str], List[str]]:
        """
        Extracts excluded garments, excluded colors, and general negative constraints.
        Examples:
          - "other than jeans" -> exclude garment jeans
          - "don't want to wear heels" -> exclude garment heels, constraint "don't want to wear heels"
          - "avoid black" -> exclude color black
          - "without leather" -> constraint "without leather"
        """
        excluded_garments = []
        excluded_colors = []
        constraints = []

        # Find negated clauses
        negated_clauses = []
        for pat in NEGATION_PATTERNS:
            for match in re.finditer(pat, text, re.IGNORECASE):
                clause = match.group(1).strip()
                full_matched = match.group(0).strip()
                negated_clauses.append((clause, full_matched))

        # Check garments within negated clauses
        for clause, full_matched in negated_clauses:
            clause_lower = " " + clause + " "
            matched_any = False

            # Check garments
            for garment in self.garments_sorted:
                g_pat = self._make_plural_regex(garment)
                if re.search(g_pat, clause_lower):
                    if garment not in excluded_garments:
                        excluded_garments.append(garment)
                    matched_any = True

            # Check colors
            for color in self.colors_sorted:
                c_pat = rf"\b{re.escape(color)}\b"
                if re.search(c_pat, clause_lower):
                    if color not in excluded_colors:
                        excluded_colors.append(color)
                    matched_any = True

            # Check materials (e.g. without leather)
            for mat in self.materials_sorted:
                m_pat = rf"\b{re.escape(mat)}\b"
                if re.search(m_pat, clause_lower):
                    constraints.append(f"exclude material: {mat}")
                    matched_any = True

            # Record constraint statement
            clean_constraint = full_matched.rstrip(",.")
            if clean_constraint not in constraints:
                constraints.append(clean_constraint)

        return excluded_garments, excluded_colors, constraints

    def _extract_occasion(self, text: str) -> OccasionModel:
        """Extracts occasion and detects formality."""
        text_padded = f" {text} "
        found_occ = None
        formality = None
        source = "unknown"

        # 1. Match specific occasion phrases (longest match first)
        for phrase in sorted(OCCASION_MAPPINGS.keys(), key=lambda x: -len(x)):
            info = OCCASION_MAPPINGS[phrase]
            pattern = rf"\b{re.escape(phrase)}\b"
            if re.search(pattern, text_padded):
                found_occ = info["val"]
                formality = info["formality"]
                source = "explicit"
                break

        # 2. Check for explicit formality overrides (e.g., "formal dinner", "casual look")
        for form_pat, form_val in FORMALITY_KEYWORDS.items():
            if re.search(form_pat, text_padded):
                formality = form_val
                # If no specific occasion was found, formality itself is explicit
                if not found_occ:
                    source = "explicit"
                break

        return OccasionModel(
            value=found_occ,
            formality=formality,
            source=source
        )

    def _extract_location(self, text: str) -> LocationModel:
        """Extracts explicit location, city, or venue. Never infers from IP."""
        # 1. Known cities & metropolitan regions
        for city in LOCATION_KEYWORDS:
            pattern = rf"\b{re.escape(city)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                return LocationModel(value=city, source="explicit")

        # 2. Explicit capitalized place names following location prepositions (e.g., "in Ithaca", "visiting Kyoto")
        cap_match = re.search(
            r"\b(?:in|visiting|traveling\s+to|travelling\s+to|flying\s+to|going\s+to)\s+([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})?)\b",
            text,
        )
        if cap_match:
            candidate = cap_match.group(1).strip()
            tokens = [t.lower() for t in candidate.split()]
            if candidate.lower() not in self._non_location_terms and not any(
                tok in self._non_location_terms for tok in tokens
            ):
                return LocationModel(value=candidate, source="explicit")

        # 3. General venue contexts (e.g. "outdoor event", "on the beach")
        loc_patterns = [
            (r"\b(outdoor|outdoors)\b", "outdoor"),
            (r"\b(beach|coast|beachside)\b", "beach"),
            (r"\b(office|workplace)\b", "office"),
            (r"\b(campus|university)\b", "campus"),
            (r"\b(rooftop)\b", "rooftop"),
            (r"\b(restaurant)\b", "restaurant")
        ]
        for pat, val in loc_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return LocationModel(value=val, source="explicit")

        return LocationModel(value=None, source="unknown")

    def _extract_time(self, text: str) -> TimeModel:
        """Resolves relative dates, weekdays, sub-day windows, and explicit ISO dates against self.ref_date."""
        # 1. Explicit ISO date (e.g. 2026-10-25 or 2026-10-25 morning)
        iso_m = re.search(
            r"\b(\d{4}-\d{2}-\d{2})(?:\s+(morning|afternoon|evening|night))?\b",
            text,
            re.IGNORECASE,
        )
        if iso_m:
            expr = iso_m.group(0).strip()
            resolved = f"{iso_m.group(1)} {iso_m.group(2).lower()}" if iso_m.group(2) else iso_m.group(1)
            return TimeModel(expression=expr, resolved=resolved, source="explicit")

        # 2. Tomorrow + optional period ("tomorrow morning", "tomorrow afternoon", "tomorrow evening", "tomorrow")
        tom_m = re.search(
            r"\btomorrow(?:\s+(morning|afternoon|evening|night))?\b",
            text,
            re.IGNORECASE,
        )
        if tom_m:
            next_day = (self.ref_date + datetime.timedelta(days=1)).isoformat()
            period = tom_m.group(1).lower() if tom_m.group(1) else None
            if period == "night":
                period = "evening"
            expr = f"tomorrow {tom_m.group(1).lower()}" if tom_m.group(1) else "tomorrow"
            resolved = f"{next_day} {period}" if period else next_day
            return TimeModel(expression=expr, resolved=resolved, source="explicit")

        # 3. Same-day windows ("this morning", "this afternoon", "tonight", "this evening", "today")
        if re.search(r"\btonight\b", text, re.IGNORECASE):
            return TimeModel(
                expression="tonight",
                resolved=f"{self.ref_date.isoformat()} evening",
                source="explicit",
            )
        this_period_m = re.search(r"\bthis\s+(morning|afternoon|evening|night)\b", text, re.IGNORECASE)
        if this_period_m:
            raw_p = this_period_m.group(1).lower()
            norm_p = "evening" if raw_p == "night" else raw_p
            return TimeModel(
                expression=f"this {raw_p}",
                resolved=f"{self.ref_date.isoformat()} {norm_p}",
                source="explicit",
            )
        if re.search(r"\btoday\b", text, re.IGNORECASE):
            return TimeModel(
                expression="today",
                resolved=self.ref_date.isoformat(),
                source="explicit",
            )

        # 4. Relative spans ("this weekend", "next weekend", "next week", "next month", "in N days/weeks")
        days_until_sat = (5 - self.ref_date.weekday()) % 7
        if re.search(r"\bnext\s+weekend\b", text, re.IGNORECASE):
            return TimeModel(
                expression="next weekend",
                resolved=(self.ref_date + datetime.timedelta(days=days_until_sat + 7)).isoformat(),
                source="explicit",
            )
        if re.search(r"\bthis\s+weekend\b", text, re.IGNORECASE):
            return TimeModel(
                expression="this weekend",
                resolved=(self.ref_date + datetime.timedelta(days=days_until_sat)).isoformat(),
                source="explicit",
            )
        if re.search(r"\bnext\s+week\b", text, re.IGNORECASE):
            return TimeModel(
                expression="next week",
                resolved=(self.ref_date + datetime.timedelta(days=7)).isoformat(),
                source="explicit",
            )
        if re.search(r"\bnext\s+month\b", text, re.IGNORECASE):
            return TimeModel(
                expression="next month",
                resolved=(self.ref_date + datetime.timedelta(days=30)).isoformat(),
                source="explicit",
            )
        in_span_m = re.search(r"\bin\s+(\d+)\s+(day|days|week|weeks|month|months)\b", text, re.IGNORECASE)
        if in_span_m:
            count = int(in_span_m.group(1))
            unit = in_span_m.group(2).lower()
            mult = 1 if unit.startswith("day") else (7 if unit.startswith("week") else 30)
            return TimeModel(
                expression=in_span_m.group(0).lower(),
                resolved=(self.ref_date + datetime.timedelta(days=count * mult)).isoformat(),
                source="explicit",
            )

        # 5. Weekdays ("Monday" .. "Sunday", including "this Saturday", "Saturday morning", etc.)
        weekdays = [
            ("Monday", 0), ("Tuesday", 1), ("Wednesday", 2), ("Thursday", 3),
            ("Friday", 4), ("Saturday", 5), ("Sunday", 6),
        ]
        for label, w_idx in weekdays:
            wd_m = re.search(
                rf"\b(this\s+|next\s+)?{label.lower()}(?:\s+(morning|afternoon|evening|night))?\b",
                text,
                re.IGNORECASE,
            )
            if wd_m:
                delta = (w_idx - self.ref_date.weekday()) % 7
                if wd_m.group(1) and "next" in wd_m.group(1).lower() and delta == 0:
                    delta = 7
                target_iso = (self.ref_date + datetime.timedelta(days=delta)).isoformat()
                period = wd_m.group(2).lower() if wd_m.group(2) else None
                if period == "night":
                    period = "evening"
                expr_prefix = wd_m.group(1).strip().lower() + " " if wd_m.group(1) else ""
                expr_suffix = f" {wd_m.group(2).lower()}" if wd_m.group(2) else ""
                return TimeModel(
                    expression=f"{expr_prefix}{label}{expr_suffix}",
                    resolved=f"{target_iso} {period}" if period else target_iso,
                    source="explicit",
                )

        return TimeModel(expression=None, resolved=None, source="unknown")

    def _extract_styles(self, text: str, occasion_model: OccasionModel) -> List[StylePreferenceItem]:
        """Extracts explicitly stated styles and reasonably inferred style directions."""
        styles = []
        text_padded = f" {text} "
        found_values = set()

        # Explicit styles
        for st in self.styles_sorted:
            pattern = rf"\b{re.escape(st)}\b"
            if re.search(pattern, text_padded, re.IGNORECASE):
                styles.append(StylePreferenceItem(value=st, source="explicit"))
                found_values.add(st)

        # Elegant keyword
        if re.search(r"\belegant\b|\belegance\b", text_padded) and "elegant" not in found_values:
            styles.append(StylePreferenceItem(value="elegant", source="explicit"))
            found_values.add("elegant")

        # Inferred style from formality if no explicit style mentioned
        if not styles and occasion_model.formality:
            if occasion_model.formality in ("formal", "black_tie"):
                styles.append(StylePreferenceItem(value="formal", source="inferred"))
            elif occasion_model.formality == "casual":
                styles.append(StylePreferenceItem(value="casual", source="inferred"))

        return styles

    def _extract_included_garments(self, text: str, excluded_garments: List[str]) -> List[str]:
        """Extracts garments that the user explicitly wants, filtering out any negated ones."""
        included = []
        text_padded = f" {text} "

        for garment in self.garments_sorted:
            if garment in excluded_garments:
                continue
            pattern = self._make_plural_regex(garment)
            if re.search(pattern, text_padded, re.IGNORECASE):
                # Ensure it wasn't part of a negated span
                included.append(garment)

        return included

    def _extract_preferred_colors(self, text: str, excluded_colors: List[str]) -> List[str]:
        """Extracts preferred colors, ensuring excluded colors are not added."""
        preferred = []
        text_padded = f" {text} "

        for color in self.colors_sorted:
            if color in excluded_colors:
                continue
            pattern = rf"\b{re.escape(color)}\b"
            if re.search(pattern, text_padded, re.IGNORECASE):
                preferred.append(color)

        return preferred

    def _extract_fit(self, text: str) -> List[str]:
        fits = []
        text_padded = f" {text} "
        for pat, val in FIT_KEYWORDS.items():
            if re.search(pat, text_padded, re.IGNORECASE):
                if val not in fits:
                    fits.append(val)
        return fits

    def _extract_functional(self, text: str) -> List[str]:
        func = []
        text_padded = f" {text} "
        for pat, val in FUNCTIONAL_KEYWORDS.items():
            if re.search(pat, text_padded, re.IGNORECASE):
                if val not in func:
                    func.append(val)
        return func

    def _extract_price(self, text: str) -> Optional[str]:
        m = re.search(r"\b(?:under|below|less\s+than)\s+\$?(\d+)(?:\s*(?:dollars|bucks|usd))?\b", text)
        if m:
            return f"budget: under ${m.group(1)}"
        return None

    def _determine_intent_and_ambiguity(
        self,
        text: str,
        occasion: OccasionModel,
        garments: List[str],
        styles: List[StylePreferenceItem],
        excluded_garments: List[str]
    ) -> Tuple[IntentModel, bool, Optional[str]]:
        """
        Determines the intent and checks if critical context is missing or ambiguous.
        E.g., "Make it more formal" without prior context requires clarification.
        """
        lower = text.lower().strip()

        # Check for modification phrases
        is_modification = bool(re.search(r"^(make\s+it|change\s+to|actually|switch\s+to|add\s+a|instead)\b", lower))
        
        # Check for styling advice
        is_styling_advice = bool(re.search(r"\b(how\s+to\s+style|how\s+do\s+i\s+wear|what\s+goes\s+with|styling\s+advice)\b", lower))

        # Check for alternative request
        is_alternative = bool(re.search(r"\b(other\s+than|alternatives?|something\s+else)\b", lower))

        # Ambiguity check: e.g. "make it more formal" with zero occasion, garments, or styles
        if is_modification and not occasion.value and not garments and len(styles) <= 1:
            return (
                IntentModel(
                    type="modification",
                    description="Request to modify an outfit",
                    is_clear=False
                ),
                True,
                "What event or outfit would you like to modify?"
            )

        if is_styling_advice:
            return (
                IntentModel(
                    type="styling_advice",
                    description=f"Styling advice for {', '.join(garments) if garments else 'outfit'}",
                    is_clear=True
                ),
                False,
                None
            )

        if is_alternative:
            return (
                IntentModel(
                    type="alternative_request",
                    description="Request for alternative outfit options",
                    is_clear=True
                ),
                False,
                None
            )

        if is_modification:
            return (
                IntentModel(
                    type="modification",
                    description="Modification to existing fashion preference",
                    is_clear=True
                ),
                False,
                None
            )

        # Standard outfit recommendation
        desc = "Outfit recommendation"
        if occasion.value:
            desc = f"An outfit for {occasion.value}"
        elif garments:
            desc = f"An outfit featuring {', '.join(garments)}"

        return (
            IntentModel(
                type="outfit_recommendation",
                description=desc,
                is_clear=True
            ),
            False,
            None
        )

    def _compute_confidence(
        self,
        occasion: OccasionModel,
        garments: List[str],
        colors: List[str],
        styles: List[StylePreferenceItem]
    ) -> float:
        points = 0.5
        if occasion.value:
            points += 0.25
        if garments:
            points += 0.15
        if colors:
            points += 0.05
        if styles:
            points += 0.05
        return min(round(points, 2), 0.99)
