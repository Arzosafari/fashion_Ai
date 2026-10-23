import unittest
from fashion_stt.extractor import FashionEntityExtractor, parse_spoken_number


class TestFashionEntityExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = FashionEntityExtractor()

    def test_spoken_number_parsing(self):
        self.assertEqual(parse_spoken_number("250"), 250.0)
        self.assertEqual(parse_spoken_number("two hundred"), 200.0)
        self.assertEqual(parse_spoken_number("one hundred fifty"), 150.0)
        self.assertEqual(parse_spoken_number("seventy five"), 75.0)

    def test_complex_outerwear_query(self):
        text = "Find me a vintage oversized black leather bomber jacket under 150 dollars in size large"
        res = self.extractor.extract(text)
        self.assertEqual(res.intent.type, "outfit_recommendation")
        self.assertIn("bomber jacket", res.garment_preferences.include)
        self.assertIn("black", res.colors.preferred)
        style_vals = [s.value for s in res.style_preferences]
        self.assertIn("vintage", style_vals)
        self.assertIn("oversized", style_vals)
        self.assertTrue(any("under $150" in c for c in res.constraints))

    def test_dress_with_occasion(self):
        text = "Show me emerald green silk slip dresses for a summer wedding"
        res = self.extractor.extract(text)
        self.assertIn("slip dress", res.garment_preferences.include)
        self.assertIn("emerald", res.colors.preferred)
        self.assertIn("green", res.colors.preferred)
        self.assertEqual(res.occasion.value, "summer wedding")
        self.assertEqual(res.occasion.formality, "formal")

    def test_negative_garment_preference(self):
        text = "I want to wear something other than jeans"
        res = self.extractor.extract(text)
        self.assertIn("jeans", res.garment_preferences.exclude)
        self.assertNotIn("jeans", res.garment_preferences.include)

    def test_negative_color_preference(self):
        text = "Give me something minimalist and avoid black"
        res = self.extractor.extract(text)
        self.assertIn("black", res.colors.excluded)
        self.assertNotIn("black", res.colors.preferred)
        self.assertTrue(any(s.value == "minimalist" for s in res.style_preferences))


if __name__ == "__main__":
    unittest.main()
