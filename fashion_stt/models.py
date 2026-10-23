"""
Pydantic Schemas for Fashion AI User Request Understanding & Contextual Integration
Defines validated machine-readable structured schemas for user requests, environmental
weather context, and aggregated recommendation context.
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
    Standard machine-readable structured JSON output representing ONLY the user's request.
    Environmental weather data is strictly kept separate in WeatherContext.
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
    missing_information: List[str] = Field(default_factory=list, description="Expected context not present in the current request (e.g., occasion, location, time).")
    clarification_needed: bool = Field(default=False, description="True if a critical detail is genuinely ambiguous.")
    clarification_question: Optional[str] = Field(default=None, description="Concise question to ask the user if clarification is needed.")

    # Metadata for pipeline debugging & evaluation
    raw_input: Optional[str] = Field(default=None, description="The exact raw text as submitted or transcribed.")
    clean_input: Optional[str] = Field(default=None, description="Normalized transcript after phonetic and fashion term fixes.")
    input_method: Optional[Literal["text", "voice"]] = Field(default="text")
    session_id: Optional[str] = Field(default=None)
    turn_index: int = Field(default=1)
    confidence_score: float = Field(default=0.9, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Environmental Weather Context Schemas (Independent of User Request Schema)
# ---------------------------------------------------------------------------

WeatherStatusLiteral = Literal[
    "ok",
    "missing_location",
    "invalid_location",
    "unsupported_forecast_date",
    "timeout",
    "network_error",
    "rate_limited",
    "invalid_credentials",
    "invalid_response",
    "missing_weather_fields",
    "provider_error",
]


class MeasurementValue(BaseModel):
    value: float = Field(description="Numeric measurement value.")
    unit: str = Field(description="Explicit measurement unit (e.g., 'C', 'km/h', 'mm', 'ratio').")


class TemperatureRange(BaseModel):
    min: float = Field(description="Minimum forecast temperature in the window.")
    max: float = Field(description="Maximum forecast temperature in the window.")
    unit: str = Field(default="C", description="Temperature unit.")


class WeatherAgentMetrics(BaseModel):
    """Preserves the exact normalized scalar metrics defined by agents.weather_agent.WeatherAgent."""
    temp: float = Field(description="Temperature in degrees Celsius.")
    humidity: float = Field(description="Relative humidity normalized to [0.0, 1.0].")
    precipitation: float = Field(description="Precipitation scaled by min(mm, 100.0) / 100.0.")
    wind_speed: float = Field(description="Wind speed at 10m in km/h.")


class ResolvedLocationModel(BaseModel):
    name: str = Field(description="Canonical resolved location label.")
    latitude: float = Field(description="WGS-84 latitude in degrees [-90, 90].")
    longitude: float = Field(description="WGS-84 longitude in degrees [-180, 180].")
    country: Optional[str] = Field(default=None, description="Country name when available.")
    timezone: Optional[str] = Field(default=None, description="IANA timezone identifier when available.")
    source: Literal["request", "settings", "coordinates"] = Field(
        default="request",
        description="Origin of the resolved location according to resolution priority."
    )


class WeatherContext(BaseModel):
    """
    Validated environmental weather context object supplied independently alongside
    FashionRequestOutput for the future Recommendation Engine.
    """
    available: bool = Field(description="True only when fresh, validated weather data is available.")
    status: WeatherStatusLiteral = Field(description="Machine-readable availability or error status code.")
    mode: Optional[Literal["current", "forecast"]] = Field(
        default=None,
        description="Whether weather data represents current observations or a date/period forecast."
    )
    message: Optional[str] = Field(
        default=None,
        description="Human-readable explanation when weather context is unavailable."
    )
    location: Optional[ResolvedLocationModel] = Field(
        default=None,
        description="Resolved geographic target location."
    )
    observed_at: Optional[str] = Field(
        default=None,
        description="Provider observation timestamp for current conditions."
    )
    forecast_for: Optional[str] = Field(
        default=None,
        description="Target ISO date or date+period window when mode == 'forecast'."
    )
    temperature: Optional[MeasurementValue] = Field(default=None)
    temperature_range: Optional[TemperatureRange] = Field(default=None)
    feels_like: Optional[MeasurementValue] = Field(default=None)
    condition: Optional[str] = Field(
        default=None,
        description="Decoded WMO weather condition label when supported by provider."
    )
    humidity: Optional[MeasurementValue] = Field(default=None)
    precipitation: Optional[MeasurementValue] = Field(default=None)
    precipitation_probability: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Forecast precipitation probability percentage (0-100) when available."
    )
    wind_speed: Optional[MeasurementValue] = Field(default=None)
    agent_metrics: Optional[WeatherAgentMetrics] = Field(
        default=None,
        description="Normalized scalar metrics matching WeatherAgent.get_weather() output."
    )
    source: Optional[str] = Field(default="open-meteo", description="Weather data provider identifier.")
    cached: bool = Field(default=False, description="True if returned from valid unexpired cache.")
    fetched_at: Optional[str] = Field(default=None, description="UTC ISO-8601 timestamp when fetched from provider.")
    cache_expires_at: Optional[str] = Field(default=None, description="UTC ISO-8601 timestamp when cache entry expires.")


class RecommendationContext(BaseModel):
    """
    Aggregated context payload combining the independent user request features and
    environmental weather context for downstream consumption by the Recommendation Engine.
    """
    request_context: FashionRequestOutput
    weather_context: WeatherContext


class UnderstandRequest(BaseModel):
    text: str = Field(..., description="The user's input text (either typed directly or voice transcript).")
    session_id: Optional[str] = Field(default=None, description="Optional conversation session ID for multi-turn follow-ups.")
    input_method: Literal["text", "voice"] = Field(default="text", description="Whether the request originated from keyboard or voice.")
    raw_transcript: Optional[str] = Field(default=None, description="Original unedited speech transcript if input was voice.")
    location: Optional[str] = Field(
        default=None,
        description="Optional explicit fallback location setting used only when the request text contains no geographic place."
    )
    latitude: Optional[float] = Field(
        default=None,
        description="Optional explicit fallback latitude (-90 to 90)."
    )
    longitude: Optional[float] = Field(
        default=None,
        description="Optional explicit fallback longitude (-180 to 180)."
    )


class UnderstandResponse(BaseModel):
    status: str = "success"
    session_id: str
    turn_index: int
    user_message: str
    assistant_response: str
    structured_data: FashionRequestOutput
    weather_context: WeatherContext
    recommendation_context: RecommendationContext
    tts_url: Optional[str] = None


class WeatherResolveRequest(BaseModel):
    """
    Validates raw Open-Meteo JSON payloads fetched via client-side HTTPS relay
    when backend containers operate in firewall-restricted environments.
    """
    session_id: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_source: Literal["request", "settings", "coordinates"] = "request"
    date_or_time: Optional[str] = None
    geocoding_payload: Optional[Dict[str, Any]] = None
    provider_payload: Optional[Dict[str, Any]] = None


class WeatherResolveResponse(BaseModel):
    weather_context: WeatherContext
    recommendation_context: Optional[RecommendationContext] = None

