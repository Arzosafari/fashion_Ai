"""
Text Encoding Pipeline for Fashion AI Recommendation System

Integrates Sentence-Transformers embeddings into the existing Fashion AI architecture.
Preserves source identity and supports future multimodal Transformer fusion.
Includes sandbox fallback mechanism for restricted environments.
"""

import logging
import uuid
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

# Try to import sentence_transformers and torch, fallback gracefully if unavailable or network blocked
try:
    from sentence_transformers import SentenceTransformer
    import torch
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

logger = logging.getLogger("fashion_stt_server.text_encoder")

class TextEncoder:
    """
    Unified text encoding pipeline integrated into the existing recommendation workflow.
    
    Model: sentence-transformers/all-MiniLM-L6-v2 (384 dimensions)
    Supports:
    1. Current user request
    2. User profile and preferences
    3. Weather context
    4. Clothing metadata
    5. Global fashion trends
    
    Preserves individual embeddings, source identities, and supports future Transformer compatibility.
    Includes fallback mechanism for sandbox/restricted network environments.
    """
    
    # Recommended model configuration
    DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION = 384
    
    def __init__(self, model_name: str = DEFAULT_MODEL, device: Optional[str] = None):
        """
        Initialize the text encoder with a pretrained Sentence Transformer model.
        Loads model once and reuses it for all requests.
        Includes fallback to mock deterministic embeddings if network/download fails.
        """
        self.model_name = model_name
        self.use_fallback = False
        
        # Use GPU if available, otherwise CPU
        if device is None:
            if SENTENCE_TRANSFORMERS_AVAILABLE and torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"
        else:
            self.device = device
            
        logger.info(f"Initializing text encoder model '{self.model_name}' on {self.device}...")
        
        # Attempt to load model, fallback if network/SSL error occurs
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer(self.model_name, device=self.device)
                logger.info(f"Text encoder model '{self.model_name}' loaded successfully.")
            except Exception as e:
                logger.warning(f"Failed to load SentenceTransformer model '{self.model_name}' ({e}). "
                               f"Falling back to deterministic mock embeddings for sandbox compatibility.")
                self.use_fallback = True
                self.model = None
        else:
            logger.warning("sentence_transformers/torch not available. Falling back to mock embeddings.")
            self.use_fallback = True
            
        # Cache for stable information (user preferences, clothing metadata)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _generate_mock_embedding(self, text: str) -> np.ndarray:
        """
        Deterministic mock embedding generator for fallback mode.
        Returns a 384-dimensional numpy array based on text hash.
        """
        # Use a deterministic seed based on text hash to ensure stability
        seed = abs(hash(text)) % (2**32)
        np.random.seed(seed)
        # Generate deterministic values in [-1, 1] range
        return np.random.uniform(-1, 1, self.EMBEDDING_DIMENSION).astype(np.float32)

    def _normalize_text(self, text: Optional[str]) -> str:
        """Normalize input text, handling empty or missing inputs."""
        if not text or not text.strip():
            return ""
        return text.strip()

    def _encode_batch(self, texts: List[str]) -> List[np.ndarray]:
        """
        Batch encode texts to 384-dimensional embeddings.
        Returns list of numpy arrays, preserving order.
        """
        if not texts:
            return []
            
        # Filter out empty texts to avoid encoding issues, but maintain mapping
        valid_texts = [t for t in texts if t.strip()]
        if not valid_texts:
            return [np.zeros(self.EMBEDDING_DIMENSION, dtype=np.float32) for _ in texts]
            
        if self.use_fallback:
            # Use deterministic mock generator
            result = []
            for text in texts:
                if text.strip():
                    result.append(self._generate_mock_embedding(text))
                else:
                    result.append(np.zeros(self.EMBEDDING_DIMENSION, dtype=np.float32))
            return result
            
        # Encode batch using actual model
        embeddings = self.model.encode(valid_texts, convert_to_numpy=True)
        
        # Reconstruct mapping with zero vectors for empty inputs
        result = []
        valid_idx = 0
        for text in texts:
            if text.strip():
                result.append(embeddings[valid_idx])
                valid_idx += 1
            else:
                result.append(np.zeros(self.EMBEDDING_DIMENSION, dtype=np.float32))
                
        return result

    def encode_user_request(self, request_text: str, session_id: str = None) -> Dict[str, Any]:
        """Encode the current user request."""
        normalized = self._normalize_text(request_text)
        if not normalized:
            return {
                "embedding": np.zeros(self.EMBEDDING_DIMENSION, dtype=np.float32).tolist(),
                "source": "user_request",
                "dimension": self.EMBEDDING_DIMENSION,
                "text": ""
            }
            
        embedding = self._encode_batch([normalized])[0]
        return {
            "embedding": embedding.tolist(),
            "source": "user_request",
            "dimension": self.EMBEDDING_DIMENSION,
            "text": normalized
        }

    def encode_user_preferences(self, profile_context: Any, session_id: str = None) -> Dict[str, Any]:
        """
        Encode user profile and preferences.
        Uses caching for stable information.
        """
        # Extract preference text from ProfileContext
        preference_texts = []
        
        if profile_context:
            # Preferred clothing styles
            if hasattr(profile_context, 'preferred_styles') and profile_context.preferred_styles:
                preference_texts.append(f"Preferred styles: {', '.join(profile_context.preferred_styles)}")
                
            # Preferred colors
            if hasattr(profile_context, 'preferred_colors') and profile_context.preferred_colors:
                preference_texts.append(f"Preferred colors: {', '.join(profile_context.preferred_colors)}")
                
            # Preferred clothing categories
            if hasattr(profile_context, 'preferred_categories') and profile_context.preferred_categories:
                preference_texts.append(f"Preferred categories: {', '.join(profile_context.preferred_categories)}")
                
            # Preferred brands
            if hasattr(profile_context, 'preferred_brands') and profile_context.preferred_brands:
                preference_texts.append(f"Preferred brands: {', '.join(profile_context.preferred_brands)}")
                
            # Fit preferences
            if hasattr(profile_context, 'fit_preferences') and profile_context.fit_preferences:
                preference_texts.append(f"Fit preferences: {', '.join(profile_context.fit_preferences)}")
                
            # Material preferences
            if hasattr(profile_context, 'material_preferences') and profile_context.material_preferences:
                preference_texts.append(f"Material preferences: {', '.join(profile_context.material_preferences)}")
                
        # Cache check for stable preferences
        cache_key = f"profile_{session_id}" if session_id else "profile_global"
        if cache_key in self._cache and "preferences" in self._cache[cache_key]:
            logger.debug("Using cached user preferences embeddings")
            return self._cache[cache_key]["preferences"]
            
        if not preference_texts:
            result = {
                "embedding": np.zeros(self.EMBEDDING_DIMENSION, dtype=np.float32).tolist(),
                "source": "user_profile",
                "dimension": self.EMBEDDING_DIMENSION,
                "records": []
            }
        else:
            embeddings = self._encode_batch(preference_texts)
            records = []
            for text, emb in zip(preference_texts, embeddings):
                records.append({
                    "text": text,
                    "embedding": emb.tolist(),
                    "dimension": self.EMBEDDING_DIMENSION
                })
                
            # Aggregate embedding (mean) for the profile
            aggregated = np.mean(embeddings, axis=0)
            
            result = {
                "embedding": aggregated.tolist(),
                "source": "user_profile",
                "dimension": self.EMBEDDING_DIMENSION,
                "records": records
            }
            
        # Cache the result
        if session_id:
            if cache_key not in self._cache:
                self._cache[cache_key] = {}
            self._cache[cache_key]["preferences"] = result
            
        return result

    def encode_weather_context(self, weather_context: Any) -> Dict[str, Any]:
        """
        Encode weather information from WeatherContext.
        Converts structured attributes into consistent textual representation.
        """
        if not weather_context or not getattr(weather_context, 'available', False):
            return {
                "embedding": np.zeros(self.EMBEDDING_DIMENSION, dtype=np.float32).tolist(),
                "source": "weather",
                "dimension": self.EMBEDDING_DIMENSION,
                "text": "No weather information available"
            }
            
        weather_texts = []
        
        # Location
        if weather_context.location and weather_context.location.name:
            weather_texts.append(f"Location: {weather_context.location.name}")
            
        # Condition
        if weather_context.condition:
            weather_texts.append(f"Condition: {weather_context.condition}")
            
        # Temperature
        if weather_context.temperature and weather_context.temperature.value is not None:
            weather_texts.append(f"Temperature: {weather_context.temperature.value}{weather_context.temperature.unit}")
            
        # Humidity
        if weather_context.humidity and weather_context.humidity.value is not None:
            weather_texts.append(f"Humidity: {weather_context.humidity.value}{weather_context.humidity.unit}")
            
        # Precipitation probability
        if weather_context.precipitation_probability is not None:
            weather_texts.append(f"Precipitation probability: {weather_context.precipitation_probability}%")
            
        # Wind speed
        if weather_context.wind_speed and weather_context.wind_speed.value is not None:
            weather_texts.append(f"Wind speed: {weather_context.wind_speed.value}{weather_context.wind_speed.unit}")
            
        # Mode and time
        if weather_context.mode:
            weather_texts.append(f"Mode: {weather_context.mode}")
        if weather_context.forecast_for:
            weather_texts.append(f"Forecast for: {weather_context.forecast_for}")
            
        combined_text = " | ".join(weather_texts) if weather_texts else "Weather context available but no specific attributes"
        
        embedding = self._encode_batch([combined_text])[0]
        
        return {
            "embedding": embedding.tolist(),
            "source": "weather",
            "dimension": self.EMBEDDING_DIMENSION,
            "text": combined_text
        }

    def encode_clothing_metadata(self, catalog_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Encode clothing metadata for multiple items.
        Preserves item_id association.
        """
        if not catalog_items:
            return []
            
        item_texts = []
        item_ids = []
        
        for item in catalog_items:
            item_id = item.get("id", "unknown")
            item_ids.append(item_id)
            
            # Construct textual representation
            parts = []
            if item.get("name"):
                parts.append(item["name"])
            if item.get("category"):
                parts.append(f"category: {item['category']}")
            if item.get("color"):
                parts.append(f"color: {item['color']}")
            if item.get("material"):
                parts.append(f"material: {item['material']}")
            if item.get("style"):
                parts.append(f"style: {', '.join(item['style'])}")
            if item.get("fit"):
                parts.append(f"fit: {item['fit']}")
            if item.get("season"):
                parts.append(f"season: {item['season']}")
            if item.get("occasion"):
                parts.append(f"occasion: {item['occasion']}")
            if item.get("description"):
                parts.append(item["description"])
                
            item_texts.append(" | ".join(parts) if parts else f"Item {item_id}")
            
        embeddings = self._encode_batch(item_texts)
        
        result = []
        for item_id, text, embedding in zip(item_ids, item_texts, embeddings):
            result.append({
                "item_id": item_id,
                "embedding": embedding.tolist(),
                "source": "clothing_metadata",
                "dimension": self.EMBEDDING_DIMENSION,
                "text": text
            })
            
        return result

    def encode_fashion_trends(self, trend_context: Any) -> List[Dict[str, Any]]:
        """
        Encode global fashion trends from TrendContext.
        Preserves trend_id/canonical_name association.
        """
        if not trend_context or not getattr(trend_context, 'available', False) or not trend_context.trends:
            return []
            
        trend_texts = []
        trend_names = []
        
        for trend in trend_context.trends:
            trend_name = trend.canonical_name or "Unknown Trend"
            trend_names.append(trend_name)
            
            parts = [trend_name]
            if trend.category:
                parts.append(f"category: {trend.category}")
            if trend.trend_score is not None:
                parts.append(f"score: {trend.trend_score:.2f}")
            if trend.lifecycle:
                parts.append(f"lifecycle: {trend.lifecycle}")
            if trend.explanation:
                parts.append(trend.explanation)
                
            trend_texts.append(" | ".join(parts))
            
        embeddings = self._encode_batch(trend_texts)
        
        result = []
        for trend_name, text, embedding in zip(trend_names, trend_texts, embeddings):
            result.append({
                "trend_id": trend_name,  # Using canonical_name as ID
                "embedding": embedding.tolist(),
                "source": "global_trends",
                "dimension": self.EMBEDDING_DIMENSION,
                "text": text
            })
            
        return result

    def encode_recommendation_context(
        self, 
        request_context: Any, 
        weather_context: Any, 
        profile_context: Any, 
        trend_context: Any,
        catalog_items: List[Dict[str, Any]] = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Main integration method: Encode all textual sources in the recommendation context.
        Returns structured output compatible with existing system and future Transformer fusion.
        """
        # 1. User Request
        user_request_emb = self.encode_user_request(
            request_context.raw_input or request_context.clean_input or "",
            session_id
        )
        
        # 2. User Profile and Preferences
        user_preferences_emb = self.encode_user_preferences(profile_context, session_id)
        
        # 3. Weather Context
        weather_emb = self.encode_weather_context(weather_context)
        
        # 4. Clothing Metadata
        clothing_items_emb = self.encode_clothing_metadata(catalog_items or [])
        
        # 5. Global Fashion Trends
        fashion_trends_emb = self.encode_fashion_trends(trend_context)
        
        # Construct final structured output
        result = {
            "user_id": getattr(profile_context, 'user_id', 'unknown') if profile_context else 'unknown',
            "text_embeddings": {
                "user_request": user_request_emb,
                "user_preferences": user_preferences_emb,
                "weather": weather_emb,
                "clothing_items": clothing_items_emb,
                "fashion_trends": fashion_trends_emb
            },
            "metadata": {
                "model_name": self.model_name,
                "embedding_dimension": self.EMBEDDING_DIMENSION,
                "encoding_status": "completed",
                "device": self.device,
                "fallback_mode": self.use_fallback
            }
        }
        
        return result

# Global encoder instance (singleton pattern)
_global_encoder: Optional[TextEncoder] = None

def get_text_encoder() -> TextEncoder:
    """Get or create the global text encoder instance."""
    global _global_encoder
    if _global_encoder is None:
        _global_encoder = TextEncoder()
    return _global_encoder
