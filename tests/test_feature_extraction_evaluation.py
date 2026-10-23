"""
Feature Extraction Evaluation Suite
Measures Intent accuracy, Precision, Recall, F1, Exact Match,
Negation preservation, Schema validity, and Clarification handling.
"""

import unittest
from typing import Dict, Any, List
from fashion_stt.extractor import FashionEntityExtractor
from fashion_stt.conversation import ConversationManager
from fashion_stt.models import FashionRequestOutput


class TestFeatureExtractionEvaluation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.extractor = FashionEntityExtractor()
        cls.conv_manager = ConversationManager(extractor=cls.extractor)

        # Diverse evaluation dataset representing real-world fashion requests
        cls.test_cases = [
            # 1. Simple request
            {
                "input": "I need something to wear to a wedding.",
                "expected_intent": "outfit_recommendation",
                "expected_occasion": "wedding",
                "expected_formality": "formal",
                "expected_garments_include": [],
                "expected_garments_exclude": [],
                "expected_colors_preferred": [],
                "expected_colors_excluded": [],
                "expected_clarification": False
            },
            # 2. Multiple simultaneous constraints
            {
                "input": "Suggest something elegant but comfortable for dinner tonight in New York.",
                "expected_intent": "outfit_recommendation",
                "expected_occasion": "dinner",
                "expected_location": "New York",
                "expected_time": "tonight",
                "expected_styles": ["elegant"],
                "expected_functional": ["comfort"],
                "expected_garments_include": [],
                "expected_garments_exclude": [],
                "expected_colors_preferred": [],
                "expected_colors_excluded": [],
                "expected_clarification": False
            },
            # 3. Negative preference on garments ("other than jeans")
            {
                "input": "I want to wear something other than jeans.",
                "expected_intent": "alternative_request",
                "expected_garments_include": [],
                "expected_garments_exclude": ["jeans"],
                "expected_colors_preferred": [],
                "expected_colors_excluded": [],
                "expected_clarification": False
            },
            # 4. Complex event with negative footwear ("no heels")
            {
                "input": "I need an outfit for a formal dinner, but I don't want to wear heels.",
                "expected_intent": "outfit_recommendation",
                "expected_occasion": "formal dinner",
                "expected_formality": "formal",
                "expected_garments_include": [],
                "expected_garments_exclude": ["heels"],
                "expected_colors_preferred": [],
                "expected_colors_excluded": [],
                "expected_clarification": False
            },
            # 5. Specific colors & style ("navy or cream", "minimalist")
            {
                "input": "Give me something minimalist, preferably in navy or cream.",
                "expected_intent": "outfit_recommendation",
                "expected_styles": ["minimalist"],
                "expected_garments_include": [],
                "expected_garments_exclude": [],
                "expected_colors_preferred": ["cream", "navy"],
                "expected_colors_excluded": [],
                "expected_clarification": False
            },
            # 6. Ambiguous request with zero prior context
            {
                "input": "Make it more formal.",
                "expected_intent": "modification",
                "expected_clarification": True
            },
            # 7. Job interview with relative temporal ("tomorrow")
            {
                "input": "I need something to wear to a job interview tomorrow.",
                "expected_intent": "outfit_recommendation",
                "expected_occasion": "job interview",
                "expected_time": "tomorrow",
                "expected_formality": "formal",
                "expected_garments_include": [],
                "expected_garments_exclude": [],
                "expected_colors_preferred": [],
                "expected_colors_excluded": [],
                "expected_clarification": False
            },
            # 8. Functional requirements ("warm outfit for an outdoor event")
            {
                "input": "I need a warm outfit for an outdoor event.",
                "expected_intent": "outfit_recommendation",
                "expected_occasion": "outdoor event",
                "expected_location": "outdoor",
                "expected_functional": ["warmth"],
                "expected_garments_include": [],
                "expected_garments_exclude": [],
                "expected_colors_preferred": [],
                "expected_colors_excluded": [],
                "expected_clarification": False
            }
        ]

    def test_benchmark_metrics(self):
        total_cases = len(self.test_cases)
        intent_matches = 0
        occasion_matches = 0
        clarification_matches = 0
        negation_matches = 0

        # Field counters for precision/recall calculation
        garment_excl_tp = 0
        garment_excl_fp = 0
        garment_excl_fn = 0

        color_pref_tp = 0
        color_pref_fp = 0
        color_pref_fn = 0

        for case in self.test_cases:
            inp = case["input"]
            out: FashionRequestOutput = self.extractor.extract(inp)

            # 1. Intent match
            if out.intent.type == case["expected_intent"]:
                intent_matches += 1

            # 2. Occasion match
            if "expected_occasion" in case:
                if out.occasion.value == case["expected_occasion"]:
                    occasion_matches += 1
            else:
                occasion_matches += 1

            # 3. Clarification match
            if out.clarification_needed == case["expected_clarification"]:
                clarification_matches += 1

            # 4. Garment exclusion metrics
            expected_excl = set(case.get("expected_garments_exclude", []))
            actual_excl = set(out.garment_preferences.exclude)
            garment_excl_tp += len(expected_excl.intersection(actual_excl))
            garment_excl_fp += len(actual_excl - expected_excl)
            garment_excl_fn += len(expected_excl - actual_excl)

            # 5. Color preference metrics
            expected_col = set(case.get("expected_colors_preferred", []))
            actual_col = set(out.colors.preferred)
            color_pref_tp += len(expected_col.intersection(actual_col))
            color_pref_fp += len(actual_col - expected_col)
            color_pref_fn += len(expected_col - actual_col)

            # 6. Negation check
            if expected_excl:
                if expected_excl.issubset(actual_excl):
                    negation_matches += 1
            else:
                negation_matches += 1

            # Schema validation check (Pydantic dumps valid schema)
            dumped = out.model_dump()
            self.assertIsInstance(dumped, dict)
            self.assertIn("intent", dumped)
            self.assertIn("occasion", dumped)

        intent_acc = intent_matches / total_cases
        occasion_acc = occasion_matches / total_cases
        clarification_acc = clarification_matches / total_cases
        negation_acc = negation_matches / total_cases

        # F1 for Garment Exclusions
        g_prec = garment_excl_tp / max(garment_excl_tp + garment_excl_fp, 1)
        g_rec = garment_excl_tp / max(garment_excl_tp + garment_excl_fn, 1)
        g_f1 = (2 * g_prec * g_rec) / max(g_prec + g_rec, 0.0001)

        # F1 for Color Preferences
        c_prec = color_pref_tp / max(color_pref_tp + color_pref_fp, 1)
        c_rec = color_pref_tp / max(color_pref_tp + color_pref_fn, 1)
        c_f1 = (2 * c_prec * c_rec) / max(c_prec + c_rec, 0.0001)

        print("\n" + "=" * 65)
        print("FEATURE EXTRACTION BENCHMARK EVALUATION RESULTS")
        print("=" * 65)
        print(f"Total Test Cases:               {total_cases}")
        print(f"Intent Classification Accuracy: {intent_acc:.1%}")
        print(f"Occasion Extraction Accuracy:   {occasion_acc:.1%}")
        print(f"Clarification / Ambiguity Acc:  {clarification_acc:.1%}")
        print(f"Negation Preservation Rate:     {negation_acc:.1%}")
        print(f"Garment Exclusion Precision:    {g_prec:.2f} | Recall: {g_rec:.2f} | F1: {g_f1:.2f}")
        print(f"Color Preferences Precision:    {c_prec:.2f} | Recall: {c_rec:.2f} | F1: {c_f1:.2f}")
        print("=" * 65)

        self.assertEqual(intent_acc, 1.0)
        self.assertEqual(clarification_acc, 1.0)
        self.assertEqual(negation_acc, 1.0)
        self.assertEqual(g_f1, 1.0)
        self.assertEqual(c_f1, 1.0)

    def test_multi_turn_followup_evaluation(self):
        """Tests sequential conversation flow: Turn 1 -> Turn 2 -> Turn 3."""
        sid = "eval_multi_turn_session"
        cm = ConversationManager(self.extractor)

        # Turn 1
        out1, resp1, _ = cm.process_request("I need an outfit for a graduation ceremony.", session_id=sid)
        self.assertEqual(out1.occasion.value, "graduation")
        self.assertEqual(len(out1.style_preferences), 0)
        self.assertEqual(len(out1.colors.excluded), 0)

        # Turn 2: Follow-up modifying style
        out2, resp2, _ = cm.process_request("Make it more minimalist.", session_id=sid)
        self.assertEqual(out2.occasion.value, "graduation")  # Occasion preserved!
        self.assertTrue(any(s.value == "minimalist" for s in out2.style_preferences))
        self.assertEqual(len(out2.colors.excluded), 0)

        # Turn 3: Follow-up adding color exclusion
        out3, resp3, _ = cm.process_request("Actually, avoid black.", session_id=sid)
        self.assertEqual(out3.occasion.value, "graduation")  # Occasion still preserved!
        self.assertTrue(any(s.value == "minimalist" for s in out3.style_preferences))
        self.assertIn("black", out3.colors.excluded)  # Exclusion added!


if __name__ == "__main__":
    unittest.main()
