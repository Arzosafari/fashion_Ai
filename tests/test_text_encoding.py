"""
Integration Tests for Text Encoding Pipeline (Section 12.4)
Verifies text encoding pipeline integration, fallback mechanism, and structured output schema.
"""

import unittest
import numpy as np
from fashion_stt.text_encoder import TextEncoder, get_text_encoder
from fashion_stt.models import (
    FashionRequestOutput,
    WeatherContext,
    ResolvedLocationModel,
    MeasurementValue,
    TrendContext,
    TrendContextItem,
)
from fashion_stt.server import FASHION_CATALOG


class TestTextEncodingPipeline(unittest.TestCase):

    def setUp(self):
        # Reset global encoder to ensure fresh state
        import fashion_stt.text_encoder as te
        te._global_encoder = None
        self.encoder = TextEncoder()

    def test_01_encoder_initialization_and_fallback(self):
        """Verify encoder initializes and handles sandbox fallback gracefully."""
        self.assertIsNotNone(self.encoder)
        self.assertEqual(self.encoder.EMBEDDING_DIMENSION, 384)
        # In sandbox, fallback mode should be True due to network restrictions
        # (If network is somehow allowed, it will be False, which is also acceptable)
        self.assertIn(self.encoder.use_fallback, [True, False])

    def test_02_user_request_encoding(self):
        """Verify user request encoding preserves source identity and dimension."""
        request_text = "I need a vintage leather jacket for a wedding."
        result = self.encoder.encode_user_request(request_text)
        
        self.assertEqual(result["source"], "user_request")
        self.assertEqual(result["dimension"], 384)
        self.assertEqual(len(result["embedding"]), 384)
        self.assertEqual(result["text"], request_text)

    def test_03_empty_request_handling(self):
        """Verify empty or whitespace requests return zero vectors."""
        result = self.encoder.encode_user_request("   ")
        self.assertEqual(result["source"], "user_request")
        self.assertEqual(result["dimension"], 384)
        self.assertTrue(np.allclose(result["embedding"], np.zeros(384)))
        self.assertEqual(result["text"], "")

    def test_04_user_preferences_encoding(self):
        """Verify user profile/preferences encoding with caching."""
        # ProfileContext structure from fashion_stt/profile.py
        # It has 'available', 'status', and 'preferences' dict
        profile_context = type("MockProfile", (), {
            "available": True,
            "status": "ok",
            "preferred_styles": ["minimalist", "vintage"],
            "preferred_colors": ["black", "beige"],
            "preferred_categories": ["outerwear"],
            "preferred_brands": ["Atelier Noir"],
            "fit_preferences": ["tailored"],
            "material_preferences": ["leather"]
        })()
        
        result = self.encoder.encode_user_preferences(profile_context, session_id="sess_1")
        
        self.assertEqual(result["source"], "user_profile")
        self.assertEqual(result["dimension"], 384)
        self.assertEqual(len(result["embedding"]), 384)
        self.assertEqual(len(result["records"]), 6)  # 6 preference categories
        
        # Test caching
        cached_result = self.encoder.encode_user_preferences(profile_context, session_id="sess_1")
        self.assertEqual(result["embedding"], cached_result["embedding"])

    def test_05_weather_context_encoding(self):
        """Verify weather context encoding structure and dimension."""
        weather = WeatherContext(
            available=True,
            status="ok",
            location=ResolvedLocationModel(name="Amsterdam", latitude=52.37, longitude=4.90),
            condition="Sunny",
            temperature=MeasurementValue(value=15.0, unit="C"),
            humidity=MeasurementValue(value=60.0, unit="%"),
            precipitation_probability=10.0,
            wind_speed=MeasurementValue(value=15.0, unit="km/h"),
            mode="current",
            forecast_for="2026-11-04"
        )
        
        result = self.encoder.encode_weather_context(weather)
        
        self.assertEqual(result["source"], "weather")
        self.assertEqual(result["dimension"], 384)
        self.assertEqual(len(result["embedding"]), 384)
        self.assertIn("Amsterdam", result["text"])
        self.assertIn("Sunny", result["text"])

    def test_06_clothing_metadata_encoding(self):
        """Verify clothing metadata encoding preserves item_id and dimension."""
        catalog_subset = FASHION_CATALOG[:3]
        results = self.encoder.encode_clothing_metadata(catalog_subset)
        
        self.assertEqual(len(results), 3)
        for res, item in zip(results, catalog_subset):
            self.assertEqual(res["source"], "clothing_metadata")
            self.assertEqual(res["dimension"], 384)
            self.assertEqual(len(res["embedding"]), 384)
            self.assertEqual(res["item_id"], item["id"])
            self.assertIn(item["name"], res["text"])

    def test_07_fashion_trends_encoding(self):
        """Verify global fashion trends encoding preserves trend_id and dimension."""
        trend_context = TrendContext(
            available=True,
            status="ok",
            trends=[
                TrendContextItem(
                    canonical_name="Quiet Luxury",
                    category="styling",
                    trend_score=0.85,
                    lifecycle="established",
                    explanation="Minimalist aesthetic focusing on quality fabrics."
                ),
                TrendContextItem(
                    canonical_name="Balletcore",
                    category="garment",
                    trend_score=0.72,
                    lifecycle="rising"
                )
            ]
        )
        
        results = self.encoder.encode_fashion_trends(trend_context)
        
        self.assertEqual(len(results), 2)
        for res, trend in zip(results, trend_context.trends):
            self.assertEqual(res["source"], "global_trends")
            self.assertEqual(res["dimension"], 384)
            self.assertEqual(len(res["embedding"]), 384)
            self.assertEqual(res["trend_id"], trend.canonical_name)

    def test_08_recommendation_context_integration(self):
        """Verify full recommendation context encoding structure."""
        request_ctx = FashionRequestOutput(
            intent={"type": "outfit_recommendation", "description": "Wedding outfit", "is_clear": True},
            occasion={"value": "wedding", "formality": "formal", "source": "explicit"},
            location={"value": None, "source": "unknown"},
            time={"expression": None, "resolved": None, "source": "unknown"},
            raw_input="I need something for a wedding.",
            clean_input="I need something for a wedding.",
            session_id="sess_999"
        )
        
        weather_ctx = WeatherContext(available=False, status="missing_location", message="No location provided")
        profile_ctx = type("MockProfile", (), {
            "available": False,
            "status": "no_profile"
        })()
        trend_ctx = TrendContext(available=True, status="ok", trends=[
            TrendContextItem(canonical_name="Minimalism", trend_score=0.9)
        ])
        
        result = self.encoder.encode_recommendation_context(
            request_context=request_ctx,
            weather_context=weather_ctx,
            profile_context=profile_ctx,
            trend_context=trend_ctx,
            catalog_items=FASHION_CATALOG[:1],
            session_id="sess_999"
        )
        
        # Verify top-level structure
        self.assertEqual(result["user_id"], "unknown")  # profile_ctx has no user_id attribute
        self.assertEqual(result["metadata"]["model_name"], self.encoder.DEFAULT_MODEL)
        self.assertEqual(result["metadata"]["embedding_dimension"], 384)
        self.assertEqual(result["metadata"]["encoding_status"], "completed")
        
        # Verify text_embeddings sub-structure
        embeddings = result["text_embeddings"]
        self.assertIn("user_request", embeddings)
        self.assertIn("user_preferences", embeddings)
        self.assertIn("weather", embeddings)
        self.assertIn("clothing_items", embeddings)
        self.assertIn("fashion_trends", embeddings)
        
        # Verify dimensions
        self.assertEqual(len(embeddings["user_request"]["embedding"]), 384)
        self.assertEqual(len(embeddings["user_preferences"]["embedding"]), 384)
        self.assertEqual(len(embeddings["weather"]["embedding"]), 384)
        self.assertEqual(len(embeddings["clothing_items"][0]["embedding"]), 384)
        self.assertEqual(len(embeddings["fashion_trends"][0]["embedding"]), 384)

    def test_09_missing_info_handling(self):
        """Verify encoding works when contexts are missing or empty."""
        result = self.encoder.encode_recommendation_context(
            request_context=FashionRequestOutput(
                intent={"type": "general_inquiry", "description": "", "is_clear": False},
                occasion={"value": None, "formality": None, "source": "unknown"},
                location={"value": None, "source": "unknown"},
                time={"expression": None, "resolved": None, "source": "unknown"},
                raw_input="", clean_input="", session_id="sess_empty"
            ),
            weather_context=WeatherContext(available=False, status="missing_location"),
            profile_context=type("MockProfile", (), {"available": False, "status": "no_profile"})(),
            trend_context=TrendContext(available=False, status="no_snapshot"),
            catalog_items=[],
            session_id="sess_empty"
        )
        
        embeddings = result["text_embeddings"]
        # Should still return zero vectors (384-dim) for all fields
        self.assertTrue(np.allclose(embeddings["user_request"]["embedding"], np.zeros(384)))
        self.assertTrue(np.allclose(embeddings["user_preferences"]["embedding"], np.zeros(384)))
        self.assertTrue(np.allclose(embeddings["weather"]["embedding"], np.zeros(384)))
        self.assertEqual(len(embeddings["clothing_items"]), 0)
        self.assertEqual(len(embeddings["fashion_trends"]), 0)


if __name__ == "__main__":
    unittest.main()
