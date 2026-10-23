"""
Pydantic Schemas for Fashion AI User Request Understanding Module
Defines the validated machine-readable structured output schema for the recommendation engine.
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


class IntentModel(BaseModel):
    type: Literal[
        "outfit_recommendation",
        "styling_advice",
        "alternative_request",
        "modification",
        "clarification_response",
        "general_inquiry"
    ] = Field(description="The primary intent of the user request.")
    description: str = Field(description="Concise description of what the user is asking for.")
    is_clear: bool = Field(default=True, description="Whether the request is sufficiently clear to proceed without clarification.")


class OccasionModel(BaseModel):
    value: Optional[str] = Field(default=None, description="The stated or inferred occasion/activity (e.g. wedding, interview, graduation).")
    formality: Optional[Literal["formal", "semi-formal", "business_casual", "casual", "black_tie", "sportswear"]] = Field(
        default=None, 
        description="The degree of formality implied or stated."
    )
    source: Literal["explicit", "inferred", "unknown"] = Field(default="unknown")


class LocationModel(BaseModel):
    value: Optional[str] = Field(default=None, description="Explicitly mentioned city, venue, country, or location context.")
    source: Literal["explicit", "unknown"] = Field(default="unknown")


class TimeModel(BaseModel):
    expression: Optional[str] = Field(default=None, description="The original temporal expression (e.g., 'tomorrow', 'tonight', 'next weekend').")
    resolved: Optional[str] = Field(default=None, description="Resolved date or time window in ISO format (YYYY-MM-DD or period).")
    source: Literal["explicit", "unknown"] = Field(default="unknown")


class StylePreferenceItem(BaseModel):
    value: str = Field(description="Style name (e.g., minimalist, casual, formal, streetwear, quiet luxury).")
    source: Literal["explicit", "inferred"] = Field(default="explicit")


class GarmentPreferencesModel(BaseModel):
    include: List[str] = Field(default_factory=list, description="Requested or preferred garments (e.g., blazer, dress, trench coat).")
    exclude: List[str] = Field(default_factory=list, description="Explicitly prohibited or avoided garments (e.g., jeans, heels).")


class ColorPreferencesModel(BaseModel):
    preferred: List[str] = Field(default_factory=list, description="Preferred colors (e.g., navy, cream, beige).")
    excluded: List[str] = Field(default_factory=list, description="Explicitly excluded colors (e.g., black, red).")


class FashionRequestOutput(BaseModel):
    """
    Standard machine-readable structured JSON output consumed by the Recommendation Engine.
    """
    intent: IntentModel
    occasion: OccasionModel
    location: LocationModel
    time: TimeModel
    style_preferences: List[StylePreferenceItem] = Field(default_factory=list)
    garment_preferences: GarmentPreferencesModel = Field(default_factory=GarmentPreferencesModel)
    colors: ColorPreferencesModel = Field(default_factory=ColorPreferencesModel)
    fit_preferences: List[str] = Field(default_factory=list, description="Fit characteristics (e.g., oversized, tailored, slim-fit, relaxed).")
    functional_requirements: List[str] = Field(default_factory=list, description="Functional needs (e.g., warmth, comfort, breathability, waterproof).")
    constraints: List[str] = Field(default_factory=list, description="Explicit constraints, budgets, or exclusions.")
    additional_details: List[str] = Field(default_factory=list, description="Meaningful details that do not fit into predefined fields.")
    missing_information: List[str] = Field(default_factory=list, description="Expected context not present in the current request (e.g., wardrobe, weather).")
    clarification_needed: bool = Field(default=False, description="True if a critical detail is genuinely ambiguous.")
    clarification_question: Optional[str] = Field(default=None, description="Concise question to ask the user if clarification is needed.")

    # Metadata for pipeline debugging & evaluation
    raw_input: Optional[str] = Field(default=None, description="The exact raw text as submitted or transcribed.")
    clean_input: Optional[str] = Field(default=None, description="Normalized transcript after phonetic and fashion term fixes.")
    input_method: Optional[Literal["text", "voice"]] = Field(default="text")
    session_id: Optional[str] = Field(default=None)
    turn_index: int = Field(default=1)
    confidence_score: float = Field(default=0.9, ge=0.0, le=1.0)


class UnderstandRequest(BaseModel):
    text: str = Field(..., description="The user's input text (either typed directly or voice transcript).")
    session_id: Optional[str] = Field(default=None, description="Optional conversation session ID for multi-turn follow-ups.")
    input_method: Literal["text", "voice"] = Field(default="text", description="Whether the request originated from keyboard or voice.")
    raw_transcript: Optional[str] = Field(default=None, description="Original unedited speech transcript if input was voice.")


class UnderstandResponse(BaseModel):
    status: str = "success"
    session_id: str
    turn_index: int
    user_message: str
    assistant_response: str
    structured_data: FashionRequestOutput
    tts_url: Optional[str] = None
