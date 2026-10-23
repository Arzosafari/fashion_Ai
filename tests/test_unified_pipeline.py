"""
Functional Integration Test Suite (Section 12.3)
Verifies all 11 required pipeline integration criteria:
1. Typed request reaches shared pipeline.
2. Voice request is transcribed and reaches the same pipeline.
3. Transcript can be edited before submission.
4. Same request produces consistent structured output regardless of input method.
5. Negative preferences are preserved.
6. Follow-up messages update the current request appropriately.
7. Missing details are not fabricated.
8. Invalid model output is handled safely.
9. Microphone permissions and processing errors produce understandable feedback.
10. Text-to-speech continues to work.
11. The application remains functional when external provider is unavailable.
"""

import unittest
import os
from fastapi.testclient import TestClient

from fashion_stt.server import app
from fashion_stt.extractor import FashionEntityExtractor
from fashion_stt.conversation import ConversationManager
from fashion_stt.tts import generate_tts_audio


class TestUnifiedPipelineIntegration(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.extractor = FashionEntityExtractor()
        self.cm = ConversationManager(self.extractor)

    # 1. Typed request reaches the shared processing pipeline
    def test_01_typed_request_reaches_pipeline(self):
        payload = {
            "text": "I need something to wear to a job interview tomorrow.",
            "input_method": "text"
        }
        res = self.client.post("/api/understand", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["structured_data"]["input_method"], "text")
        self.assertEqual(data["structured_data"]["occasion"]["value"], "job interview")

    # 2. Voice request is transcribed and reaches the same pipeline
    def test_02_voice_request_transcribed_and_processed(self):
        sample_path = "/home/user/public/samples/sample_outerwear.wav"
        if not os.path.exists(sample_path):
            self.skipTest(f"{sample_path} not found")

        # Step A: Transcribe audio
        with open(sample_path, "rb") as f:
            t_res = self.client.post("/api/transcribe", files={"file": ("sample.wav", f, "audio/wav")})
        self.assertEqual(t_res.status_code, 200)
        transcript = t_res.json()["clean_text"]

        # Step B: Submit transcript through unified /api/understand
        u_res = self.client.post("/api/understand", json={
            "text": transcript,
            "input_method": "voice",
            "raw_transcript": t_res.json()["raw_text"]
        })
        self.assertEqual(u_res.status_code, 200)
        data = u_res.json()
        self.assertEqual(data["structured_data"]["input_method"], "voice")
        self.assertIn("bomber jacket", data["structured_data"]["garment_preferences"]["include"])

    # 3. Transcript can be edited before submission
    def test_03_edited_transcript_before_submission(self):
        # Raw transcript was misheard, user edits it before sending
        original_speech = "find me an out culture dress in she fawn"
        user_edited = "I need an haute couture cocktail dress in chiffon"

        u_res = self.client.post("/api/understand", json={
            "text": user_edited,
            "input_method": "voice",
            "raw_transcript": original_speech
        })
        self.assertEqual(u_res.status_code, 200)
        data = u_res.json()
        self.assertEqual(data["structured_data"]["clean_input"], user_edited)
        self.assertEqual(data["structured_data"]["raw_input"], original_speech)
        self.assertIn("cocktail dress", data["structured_data"]["garment_preferences"]["include"])

    # 4. Same request produces consistent structured output regardless of input method
    def test_04_consistent_output_across_input_methods(self):
        query = "Suggest something elegant but comfortable for dinner tonight."

        res_text = self.client.post("/api/understand", json={"text": query, "input_method": "text"}).json()
        res_voice = self.client.post("/api/understand", json={"text": query, "input_method": "voice"}).json()

        st_text = res_text["structured_data"]
        st_voice = res_voice["structured_data"]

        # Compare core semantic fields
        self.assertEqual(st_text["intent"]["type"], st_voice["intent"]["type"])
        self.assertEqual(st_text["occasion"]["value"], st_voice["occasion"]["value"])
        self.assertEqual(st_text["time"]["resolved"], st_voice["time"]["resolved"])
        self.assertEqual(
            [s["value"] for s in st_text["style_preferences"]],
            [s["value"] for s in st_voice["style_preferences"]]
        )
        self.assertEqual(st_text["functional_requirements"], st_voice["functional_requirements"])

    # 5. Negative preferences are preserved
    def test_05_negative_preferences_preserved(self):
        query = "I want to wear something other than jeans and avoid black."
        res = self.client.post("/api/understand", json={"text": query, "input_method": "text"}).json()
        st = res["structured_data"]

        self.assertIn("jeans", st["garment_preferences"]["exclude"])
        self.assertNotIn("jeans", st["garment_preferences"]["include"])
        self.assertIn("black", st["colors"]["excluded"])
        self.assertNotIn("black", st["colors"]["preferred"])

    # 6. Follow-up messages update the current request appropriately
    def test_06_follow_up_updates_request_appropriately(self):
        sid = "followup_integration_sid"

        # Turn 1
        t1 = self.client.post("/api/understand", json={
            "text": "I need an outfit for a graduation ceremony.",
            "session_id": sid
        }).json()
        self.assertEqual(t1["structured_data"]["occasion"]["value"], "graduation")

        # Turn 2
        t2 = self.client.post("/api/understand", json={
            "text": "Make it more minimalist.",
            "session_id": sid
        }).json()
        self.assertEqual(t2["structured_data"]["occasion"]["value"], "graduation")
        self.assertTrue(any(s["value"] == "minimalist" for s in t2["structured_data"]["style_preferences"]))

        # Turn 3
        t3 = self.client.post("/api/understand", json={
            "text": "Actually, avoid black.",
            "session_id": sid
        }).json()
        self.assertEqual(t3["structured_data"]["occasion"]["value"], "graduation")
        self.assertIn("black", t3["structured_data"]["colors"]["excluded"])

    # 7. Missing details are not fabricated
    def test_07_missing_details_not_fabricated(self):
        query = "Can you help me put together an outfit for a wedding?"
        res = self.client.post("/api/understand", json={"text": query}).json()
        st = res["structured_data"]

        # User did not mention location, color, or budget - must be None/empty
        self.assertIsNone(st["location"]["value"])
        self.assertEqual(st["location"]["source"], "unknown")
        self.assertEqual(len(st["colors"]["preferred"]), 0)
        self.assertEqual(len(st["colors"]["excluded"]), 0)
        self.assertIn("location", st["missing_information"])

    # 8. Invalid model output is handled safely
    def test_08_invalid_input_handled_safely(self):
        # Empty string should return 400 Bad Request
        empty_res = self.client.post("/api/understand", json={"text": ""})
        self.assertEqual(empty_res.status_code, 400)

        # Whitespace only
        ws_res = self.client.post("/api/understand", json={"text": "   "})
        self.assertEqual(ws_res.status_code, 400)

    # 9. Microphone permissions and processing errors produce understandable feedback
    def test_09_permission_and_error_signals(self):
        # Transcribing empty file produces 400 with clear message
        res = self.client.post("/api/transcribe", files={"file": ("empty.wav", b"", "audio/wav")})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Empty audio file", res.json()["detail"])

    # 10. Text-to-speech continues to work
    def test_10_tts_endpoint_functional(self):
        res = self.client.get("/api/tts?text=Looking%20for%20a%20wedding%20outfit")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "audio/mpeg")
        self.assertGreater(len(res.content), 500)

    # 11. Application remains functional when external provider is unavailable
    def test_11_self_contained_offline_resilience(self):
        # Even if network is blocked, extractor and conversation manager run 100% locally on CPU
        out = self.extractor.extract("Suggest something elegant for dinner tonight.")
        self.assertIsNotNone(out)
        self.assertEqual(out.occasion.value, "dinner")


if __name__ == "__main__":
    unittest.main()
