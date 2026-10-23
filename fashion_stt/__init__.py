"""
Fashion AI — User Request Understanding Module
Provides real-time English speech-to-text, text input parsing, conversational state memory,
negation preservation, and structured JSON output for the outfit recommendation engine.
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
    UnderstandRequest,
    UnderstandResponse
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
    FASHION_BRANDS
)
from .tts import generate_tts_audio
from .server import create_app, app

__version__ = "2.0.0"
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
    "UnderstandRequest",
    "UnderstandResponse",
    "correct_fashion_text",
    "get_all_fashion_terms",
    "get_fashion_grammar_list",
    "generate_tts_audio",
    "create_app",
    "app"
]
