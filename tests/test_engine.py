import unittest
import os
from fashion_stt.engine import RealtimeTranscriber


class TestTranscriberEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.transcriber = RealtimeTranscriber()

    def test_transcribe_audio_sample(self):
        sample_path = "/home/user/public/samples/sample_outerwear.wav"
        if not os.path.exists(sample_path):
            self.skipTest(f"Sample file {sample_path} not found")

        result = self.transcriber.transcribe_file(sample_path)
        self.assertIsNotNone(result)
        self.assertIn("clean_text", result)
        self.assertTrue(len(result["clean_text"]) > 0)
        self.assertIn("bomber jacket", result["entities"]["garments"])
        self.assertIn("leather", result["entities"]["materials"])
        self.assertIn("black", result["entities"]["colors"])

    def test_chunk_streaming(self):
        sample_path = "/home/user/public/samples/sample_dress.wav"
        if not os.path.exists(sample_path):
            self.skipTest(f"Sample file {sample_path} not found")

        pcm_data = self.transcriber._to_pcm16(sample_path)
        rec = self.transcriber.create_recognizer()

        chunk_size = 3200  # 100ms
        partials = []
        finals = []

        for i in range(0, len(pcm_data), chunk_size):
            chunk = pcm_data[i:i + chunk_size]
            event = self.transcriber.process_chunk(rec, chunk)
            if event["type"] == "partial":
                partials.append(event["clean_text"])
            elif event["type"] == "final":
                finals.append(event["clean_text"])

        final_event = self.transcriber.finalize_stream(rec)
        if final_event["clean_text"]:
            finals.append(final_event["clean_text"])

        full_result = " ".join(finals)
        self.assertIn("silk", full_result.lower())
        self.assertIn("dress", full_result.lower())


if __name__ == "__main__":
    unittest.main()
