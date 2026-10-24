# attribute_vocab.py
"""
Attribute vocabularies used by the training targets.

Only INTRINSIC visual attributes (color / material / pattern) may be read from
or predicted into the text: the MLM pool below contains just those buckets.
Style, season and occasion are NEVER text attributes by design -- style and
season must be recognized from the image (or arrive with the recommendation
context), and the occasion is a property of the event, not of the garment.
SEASONS stays only as a taxonomy for the hide_season input guardrail and for
downstream analysis (there is no season training head). STYLES stays only as a
taxonomy for downstream analysis. Neither may enter a caption or a prompt.

DISCOVERED words: while captioning, the agent collects VLM words outside these
lists into vocab_discovered.json (same folder). Words seen at least
MIN_DISCOVERED_COUNT times join the MLM pool automatically; the canonical lists
above stay hand-curated. Promote a discovered word by moving it here and
deleting it from the json.
"""
import json
import os
from typing import List

SEASONS: List[str] = ["spring", "summer", "autumn", "winter"]   # taxonomy + hide_season guardrail (no training head uses it)
# navy before blue: same length, the specific shade must win first-match scans
COLORS: List[str] = ["black", "white", "grey", "navy", "blue", "red", "pink", "green",
                     "yellow", "brown", "beige", "burgundy"]
MATERIALS: List[str] = ["wool", "denim", "leather", "linen", "silk", "knit", "cashmere",
                        "polyester", "velvet", "satin", "cotton", "fleece"]
PATTERNS: List[str] = ["striped", "plaid", "floral", "checkered", "printed", "ribbed",
                       "polka dot", "solid"]
STYLES: List[str] = ["formal", "sporty", "casual"]  # taxonomy only: never a text attribute

ATTRIBUTE_WORDS: List[str] = COLORS + MATERIALS + PATTERNS   # words the MLM is encouraged to predict

# --- auto-discovered words (written by llm_description_agent.py, reviewed by a human) ---
MIN_DISCOVERED_COUNT = 5
DISCOVERED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocab_discovered.json")


def _load_discovered() -> List[str]:
    try:
        with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
            counts = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(counts, dict):
        return []
    return sorted(w for w, c in counts.items()
                  if isinstance(w, str) and isinstance(c, int) and c >= MIN_DISCOVERED_COUNT)


DISCOVERED: List[str] = _load_discovered()

ATTRIBUTE_WORDS = ATTRIBUTE_WORDS + DISCOVERED

ALLOWED_MASK_WORDS = set(ATTRIBUTE_WORDS)  # MLM masks intrinsic attributes, never grammar/style/season

# word -> same-bucket alternatives (for ITM-style word swaps; kept for API compatibility)
NEGATIVE_POOL = {w: [v for v in bucket if v != w]
                 for bucket in (COLORS, MATERIALS, PATTERNS, STYLES, SEASONS, DISCOVERED) for w in bucket}
