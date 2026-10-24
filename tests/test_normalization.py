from trend_system.normalization.taxonomy import lookup_canonical
from trend_system.extraction.fashion_extractor import extract_fashion_attributes

def test_lookup_canonical():
    canon, cat = lookup_canonical("شلوار گشاد")
    assert canon == "wide_leg_bottom"
    canon2, cat2 = lookup_canonical("wide leg trousers")
    assert canon2 == "wide_leg_bottom"

def test_extraction_persian():
    text = "مانتو با شلوار گشاد جین ست زیبایی است"
    found = extract_fashion_attributes(text, language="fa")
    assert "wide_leg_bottom" in found["trend_candidates"] or "wide_leg_bottom" in found["silhouettes"]
    assert "manteau" in found["trend_candidates"] or "manteau" in found["garments"]

def test_extraction_english():
    text = "The wide-leg trousers and linen blazer are trending"
    found = extract_fashion_attributes(text, language="en")
    assert "wide_leg_bottom" in found["trend_candidates"]
    assert "linen" in found["trend_candidates"]
