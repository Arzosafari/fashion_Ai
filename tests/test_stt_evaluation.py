"""
Speech-to-Text Evaluation Suite
Measures Word Error Rate (WER), fashion domain accuracy, and negation preservation
across reference audio transcripts using standard dynamic programming Levenshtein distance.
"""

import unittest
import os
import re
from typing import List, Tuple
from fashion_stt.engine import RealtimeTranscriber
from fashion_stt.lexicon import correct_fashion_text


def calculate_wer(reference: str, hypothesis: str) -> Tuple[float, int, int, int, int]:
    """
    Computes Word Error Rate (WER) using Levenshtein distance at word level.
    Returns: (wer_score, substitutions, deletions, insertions, total_ref_words)
    """
    # Normalize punctuation and lowercase
    ref_words = re.sub(r"[^\w\s]", "", reference.lower()).split()
    hyp_words = re.sub(r"[^\w\s]", "", hypothesis.lower()).split()

    r_len = len(ref_words)
    h_len = len(hyp_words)

    if r_len == 0:
        return (0.0 if h_len == 0 else 1.0, 0, 0, h_len, 0)

    # Dynamic programming matrix (Levenshtein)
    dp = [[0] * (h_len + 1) for _ in range(r_len + 1)]

    for i in range(r_len + 1):
        dp[i][0] = i
    for j in range(h_len + 1):
        dp[0][j] = j

    for i in range(1, r_len + 1):
        for j in range(1, h_len + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                substitution = dp[i - 1][j - 1] + 1
                insertion = dp[i][j - 1] + 1
                deletion = dp[i - 1][j] + 1
                dp[i][j] = min(substitution, insertion, deletion)

    distance = dp[r_len][h_len]
    wer = distance / r_len
    return wer, distance, r_len


class TestSTTEvaluation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.transcriber = RealtimeTranscriber()
        # Reference audio test set with verified ground-truth transcripts
        cls.eval_set = [
            {
                "file": "/home/user/public/samples/sample_outerwear.wav",
                "reference": "find me an oversized vintage leather bomber jacket in black under one hundred fifty dollars",
                "key_garment": "bomber jacket",
                "key_material": "leather",
                "key_color": "black"
            },
            {
                "file": "/home/user/public/samples/sample_dress.wav",
                "reference": "show me an emerald green silk slip dress for a summer wedding",
                "key_garment": "slip dress",
                "key_material": "silk",
                "key_color": "emerald"
            },
            {
                "file": "/home/user/public/samples/sample_houndstooth.wav",
                "reference": "looking for a tailored houndstooth blazer in beige under two hundred dollars",
                "key_garment": "blazer",
                "key_pattern": "houndstooth",
                "key_color": "beige"
            },
            {
                "file": "/home/user/public/samples/sample_knitwear.wav",
                "reference": "i want a pure cashmere beige turtleneck sweater in size medium",
                "key_garment": "turtleneck",
                "key_material": "cashmere"
            }
        ]

    def test_wer_on_fashion_audio_corpus(self):
        total_words = 0
        total_errors = 0
        results = []

        print("\n" + "=" * 65)
        print("SPEECH-TO-TEXT WORD ERROR RATE (WER) EVALUATION")
        print("=" * 65)

        for sample in self.eval_set:
            path = sample["file"]
            if not os.path.exists(path):
                continue

            ref = sample["reference"]
            trans_res = self.transcriber.transcribe_file(path)
            hyp = trans_res["clean_text"]

            wer, dist, n_words = calculate_wer(ref, hyp)
            total_words += n_words
            total_errors += dist

            results.append({
                "sample": os.path.basename(path),
                "reference": ref,
                "hypothesis": hyp,
                "wer": wer
            })

            print(f"Sample:    {os.path.basename(path)}")
            print(f"Ref:       {ref}")
            print(f"Hyp:       {hyp}")
            print(f"Sample WER:{wer:.2%}\n")

            # Verify fashion terms survived
            if "key_garment" in sample:
                self.assertIn(sample["key_garment"], hyp.lower())

        corpus_wer = total_errors / max(total_words, 1)
        print(f"Overall Corpus WER: {corpus_wer:.2%} ({total_errors} errors across {total_words} words)")
        print("=" * 65)

        # Baseline constraint: Corpus WER must be under 15% on clean fashion audio
        self.assertLess(corpus_wer, 0.15)

    def test_negation_preservation_in_cleaning(self):
        """Verifies that transcript cleanup never strips meaningful negation words."""
        test_phrases = [
            "I want to wear something other than jeans",
            "I do not want to wear heels",
            "Give me something without black or red",
            "Suggest an outfit except skirts and dresses"
        ]

        for phrase in test_phrases:
            cleaned, _ = correct_fashion_text(phrase)
            lower_clean = cleaned.lower()
            # Ensure negations remain intact
            self.assertTrue(
                any(neg in lower_clean for neg in ["other than", "not", "without", "except"]),
                f"Negation was stripped from: {phrase}"
            )


if __name__ == "__main__":
    unittest.main()
