import unittest
from fashion_stt.lexicon import correct_fashion_text, get_all_fashion_terms


class TestFashionLexicon(unittest.TestCase):

    def test_houndstooth_correction(self):
        text = "show me a hound tooth blazer"
        corr, fixes = correct_fashion_text(text)
        self.assertEqual(corr, "show me a houndstooth blazer")
        self.assertTrue(any(f["corrected"] == "houndstooth" for f in fixes))

    def test_haute_couture_and_chiffon(self):
        text = "looking for out culture gown in she fawn"
        corr, fixes = correct_fashion_text(text)
        self.assertEqual(corr, "looking for haute couture gown in chiffon")

    def test_cashmere_and_culottes(self):
        text = "pure kashmir sweater and cool lots"
        corr, fixes = correct_fashion_text(text)
        self.assertEqual(corr, "pure cashmere sweater and culottes")

    def test_balletcore_and_y2k(self):
        text = "i love ballet core and why two k fashion"
        corr, fixes = correct_fashion_text(text)
        self.assertEqual(corr, "i love balletcore and y2k fashion")

    def test_brands(self):
        text = "designer bags from saint lorant and botega"
        corr, fixes = correct_fashion_text(text)
        self.assertEqual(corr, "designer bags from Saint Laurent and Bottega Veneta")

    def test_vocabulary_size(self):
        terms = get_all_fashion_terms()
        self.assertGreater(len(terms), 100)


if __name__ == "__main__":
    unittest.main()
