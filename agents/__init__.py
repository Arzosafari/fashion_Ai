"""
Agents package for Fashion AI contextual modules.
Exposes the Open-Meteo WeatherAgent and typed weather client errors.
"""

from .weather_agent import (
    WeatherAgent,
    WeatherAgentError,
    InvalidCoordinatesError,
    UnsupportedForecastError,
    WeatherTimeoutError,
    WeatherNetworkError,
    WeatherRateLimitError,
    WeatherAuthError,
    WeatherResponseError,
    WeatherMissingFieldsError,
    WMO_WEATHER_CODES,
    validate_coordinates,
)

__all__ = [
    "WeatherAgent",
    "WeatherAgentError",
    "InvalidCoordinatesError",
    "UnsupportedForecastError",
    "WeatherTimeoutError",
    "WeatherNetworkError",
    "WeatherRateLimitError",
    "WeatherAuthError",
    "WeatherResponseError",
    "WeatherMissingFieldsError",
    "WMO_WEATHER_CODES",
    "validate_coordinates",
]
