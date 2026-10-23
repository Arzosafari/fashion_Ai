"""
Fashion AI — User Request Understanding & Weather Context Integration Module
Provides real-time English speech-to-text, text input parsing, conversational state memory,
negation preservation, independent Open-Meteo environmental weather context retrieval,
and validated JSON outputs for the outfit recommendation engine.
"""

from .engine import RealtimeTranscriber
from .extractor import FashionEntityExtractor
from .conversation import ConversationManager, ConversationSession
from .models import (
    FashionRequestOutput,
    IntentModel,
    OccasionModel,
    LocationModel,
    TimeModel,
    StylePreferenceItem,
    GarmentPreferencesModel,
    ColorPreferencesModel,
    MeasurementValue,
    TemperatureRange,
    WeatherAgentMetrics,
    ResolvedLocationModel,
    WeatherContext,
    RecommendationContext,
    UnderstandRequest,
    UnderstandResponse,
)
from .weather_context import (
    WeatherConfig,
    WeatherCache,
    LocationResolver,
    WeatherContextService,
    ContextIntegrator,
    get_weather_context,
    parse_forecast_target,
    MissingLocationError,
    InvalidLocationError,
)
from .lexicon import (
    correct_fashion_text,
    get_all_fashion_terms,
    get_fashion_grammar_list,
    FASHION_CATEGORIES,
    FASHION_MATERIALS,
    FASHION_STYLES,
    FASHION_PATTERNS,
    FASHION_COLORS,
    FASHION_BRANDS,
)
from .tts import generate_tts_audio
from .server import create_app, app

__version__ = "2.1.0"
__all__ = [
    "RealtimeTranscriber",
    "FashionEntityExtractor",
    "ConversationManager",
    "ConversationSession",
    "FashionRequestOutput",
    "IntentModel",
    "OccasionModel",
    "LocationModel",
    "TimeModel",
    "StylePreferenceItem",
    "GarmentPreferencesModel",
    "ColorPreferencesModel",
    "MeasurementValue",
    "TemperatureRange",
    "WeatherAgentMetrics",
    "ResolvedLocationModel",
    "WeatherContext",
    "RecommendationContext",
    "UnderstandRequest",
    "UnderstandResponse",
    "WeatherConfig",
    "WeatherCache",
    "LocationResolver",
    "WeatherContextService",
    "ContextIntegrator",
    "get_weather_context",
    "parse_forecast_target",
    "MissingLocationError",
    "InvalidLocationError",
    "correct_fashion_text",
    "get_all_fashion_terms",
    "get_fashion_grammar_list",
    "generate_tts_audio",
    "create_app",
    "app",
]
