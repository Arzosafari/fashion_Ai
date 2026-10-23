"""
Weather Context Module Integration for Fashion AI
Connects the existing Open-Meteo WeatherAgent (agents/weather_agent.py) to the
Fashion AI request lifecycle through clean, modular, decoupled interfaces:
  - WeatherConfig: environment-driven configuration without hardcoded locations or secrets
  - LocationResolver: strict priority resolution (explicit request -> settings/provider -> unavailable)
  - WeatherCache: bounded thread-safe TTL cache preventing stale data from being served as live weather
  - WeatherContextService: clean `get_weather_context(location, date_or_time)` interface
  - ContextIntegrator: aggregates `FashionRequestOutput` + `WeatherContext` into `RecommendationContext`
"""

import datetime
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal, Optional, Tuple, Union

import requests

from agents.weather_agent import (
    InvalidCoordinatesError,
    UnsupportedForecastError,
    WeatherAgent,
    WeatherAgentError,
    WeatherAuthError,
    WeatherMissingFieldsError,
    WeatherNetworkError,
    WeatherRateLimitError,
    WeatherResponseError,
    WeatherTimeoutError,
    validate_coordinates,
)
from .models import (
    FashionRequestOutput,
    MeasurementValue,
    RecommendationContext,
    ResolvedLocationModel,
    TemperatureRange,
    WeatherAgentMetrics,
    WeatherContext,
    WeatherStatusLiteral,
)

logger = logging.getLogger("fashion_ai.weather_context")


class LocationResolutionError(Exception):
    """Base error during location resolution."""


class MissingLocationError(LocationResolutionError):
    """Raised when no explicit or configured geographic location is available."""


class InvalidLocationError(LocationResolutionError):
    """Raised when a supplied location or coordinate pair cannot be validated or geocoded."""


# Non-geographic venue/setting words extracted by NLP that must never be geocoded as cities
NON_GEOGRAPHIC_VENUES = frozenset({
    "outdoor",
    "outdoors",
    "indoor",
    "indoors",
    "beach",
    "coast",
    "beachside",
    "office",
    "workplace",
    "campus",
    "university",
    "rooftop",
    "restaurant",
    "home",
    "venue",
})

# Verified WGS-84 city coordinates for fast, deterministic resolution without extra round-trips
CITY_GAZETTEER: Dict[str, Dict[str, Any]] = {
    "tehran": {"name": "Tehran", "latitude": 35.6892, "longitude": 51.3890, "country": "Iran", "timezone": "Asia/Tehran"},
    "shiraz": {"name": "Shiraz", "latitude": 29.5918, "longitude": 52.5837, "country": "Iran", "timezone": "Asia/Tehran"},
    "isfahan": {"name": "Isfahan", "latitude": 32.6546, "longitude": 51.6680, "country": "Iran", "timezone": "Asia/Tehran"},
    "tabriz": {"name": "Tabriz", "latitude": 38.0800, "longitude": 46.2919, "country": "Iran", "timezone": "Asia/Tehran"},
    "mashhad": {"name": "Mashhad", "latitude": 36.2605, "longitude": 59.6168, "country": "Iran", "timezone": "Asia/Tehran"},
    "karaj": {"name": "Karaj", "latitude": 35.8400, "longitude": 50.9391, "country": "Iran", "timezone": "Asia/Tehran"},
    "rasht": {"name": "Rasht", "latitude": 37.2808, "longitude": 49.5832, "country": "Iran", "timezone": "Asia/Tehran"},
    "yazd": {"name": "Yazd", "latitude": 31.8974, "longitude": 54.3569, "country": "Iran", "timezone": "Asia/Tehran"},
    "kerman": {"name": "Kerman", "latitude": 30.2839, "longitude": 57.0834, "country": "Iran", "timezone": "Asia/Tehran"},
    "ahvaz": {"name": "Ahvaz", "latitude": 31.3183, "longitude": 48.6706, "country": "Iran", "timezone": "Asia/Tehran"},
    "qom": {"name": "Qom", "latitude": 34.6416, "longitude": 50.8746, "country": "Iran", "timezone": "Asia/Tehran"},
    "kish": {"name": "Kish", "latitude": 26.5578, "longitude": 53.9801, "country": "Iran", "timezone": "Asia/Tehran"},
    "boston": {"name": "Boston", "latitude": 42.3601, "longitude": -71.0589, "country": "United States", "timezone": "America/New_York"},
    "new york": {"name": "New York", "latitude": 40.7128, "longitude": -74.0060, "country": "United States", "timezone": "America/New_York"},
    "nyc": {"name": "New York", "latitude": 40.7128, "longitude": -74.0060, "country": "United States", "timezone": "America/New_York"},
    "dallas": {"name": "Dallas", "latitude": 32.7767, "longitude": -96.7970, "country": "United States", "timezone": "America/Chicago"},
    "fort worth": {"name": "Fort Worth", "latitude": 32.7555, "longitude": -97.3308, "country": "United States", "timezone": "America/Chicago"},
    "san antonio": {"name": "San Antonio", "latitude": 29.4241, "longitude": -98.4936, "country": "United States", "timezone": "America/Chicago"},
    "plano": {"name": "Plano", "latitude": 33.0198, "longitude": -96.6989, "country": "United States", "timezone": "America/Chicago"},
    "arlington": {"name": "Arlington", "latitude": 32.7357, "longitude": -97.1081, "country": "United States", "timezone": "America/Chicago"},
    "frisco": {"name": "Frisco", "latitude": 33.1507, "longitude": -96.8236, "country": "United States", "timezone": "America/Chicago"},
    "irving": {"name": "Irving", "latitude": 32.8140, "longitude": -96.9489, "country": "United States", "timezone": "America/Chicago"},
    "austin": {"name": "Austin", "latitude": 30.2672, "longitude": -97.7431, "country": "United States", "timezone": "America/Chicago"},
    "houston": {"name": "Houston", "latitude": 29.7604, "longitude": -95.3698, "country": "United States", "timezone": "America/Chicago"},
    "chicago": {"name": "Chicago", "latitude": 41.8781, "longitude": -87.6298, "country": "United States", "timezone": "America/Chicago"},
    "los angeles": {"name": "Los Angeles", "latitude": 34.0522, "longitude": -118.2437, "country": "United States", "timezone": "America/Los_Angeles"},
    "san francisco": {"name": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "country": "United States", "timezone": "America/Los_Angeles"},
    "seattle": {"name": "Seattle", "latitude": 47.6062, "longitude": -122.3321, "country": "United States", "timezone": "America/Los_Angeles"},
    "miami": {"name": "Miami", "latitude": 25.7617, "longitude": -80.1918, "country": "United States", "timezone": "America/New_York"},
    "washington": {"name": "Washington", "latitude": 38.9072, "longitude": -77.0369, "country": "United States", "timezone": "America/New_York"},
    "philadelphia": {"name": "Philadelphia", "latitude": 39.9526, "longitude": -75.1652, "country": "United States", "timezone": "America/New_York"},
    "denver": {"name": "Denver", "latitude": 39.7392, "longitude": -104.9903, "country": "United States", "timezone": "America/Denver"},
    "atlanta": {"name": "Atlanta", "latitude": 33.7490, "longitude": -84.3880, "country": "United States", "timezone": "America/New_York"},
    "phoenix": {"name": "Phoenix", "latitude": 33.4484, "longitude": -112.0740, "country": "United States", "timezone": "America/Phoenix"},
    "san diego": {"name": "San Diego", "latitude": 32.7157, "longitude": -117.1611, "country": "United States", "timezone": "America/Los_Angeles"},
    "portland": {"name": "Portland", "latitude": 45.5152, "longitude": -122.6784, "country": "United States", "timezone": "America/Los_Angeles"},
    "las vegas": {"name": "Las Vegas", "latitude": 36.1699, "longitude": -115.1398, "country": "United States", "timezone": "America/Los_Angeles"},
    "minneapolis": {"name": "Minneapolis", "latitude": 44.9778, "longitude": -93.2650, "country": "United States", "timezone": "America/Chicago"},
    "detroit": {"name": "Detroit", "latitude": 42.3314, "longitude": -83.0458, "country": "United States", "timezone": "America/Detroit"},
    "toronto": {"name": "Toronto", "latitude": 43.6532, "longitude": -79.3832, "country": "Canada", "timezone": "America/Toronto"},
    "montreal": {"name": "Montreal", "latitude": 45.5017, "longitude": -73.5673, "country": "Canada", "timezone": "America/Toronto"},
    "vancouver": {"name": "Vancouver", "latitude": 49.2827, "longitude": -123.1207, "country": "Canada", "timezone": "America/Vancouver"},
    "mexico city": {"name": "Mexico City", "latitude": 19.4326, "longitude": -99.1332, "country": "Mexico", "timezone": "America/Mexico_City"},
    "london": {"name": "London", "latitude": 51.5074, "longitude": -0.1278, "country": "United Kingdom", "timezone": "Europe/London"},
    "edinburgh": {"name": "Edinburgh", "latitude": 55.9533, "longitude": -3.1883, "country": "United Kingdom", "timezone": "Europe/London"},
    "manchester": {"name": "Manchester", "latitude": 53.4808, "longitude": -2.2426, "country": "United Kingdom", "timezone": "Europe/London"},
    "dublin": {"name": "Dublin", "latitude": 53.3498, "longitude": -6.2603, "country": "Ireland", "timezone": "Europe/Dublin"},
    "paris": {"name": "Paris", "latitude": 48.8566, "longitude": 2.3522, "country": "France", "timezone": "Europe/Paris"},
    "milan": {"name": "Milan", "latitude": 45.4642, "longitude": 9.1900, "country": "Italy", "timezone": "Europe/Rome"},
    "rome": {"name": "Rome", "latitude": 41.9028, "longitude": 12.4964, "country": "Italy", "timezone": "Europe/Rome"},
    "venice": {"name": "Venice", "latitude": 45.4408, "longitude": 12.3155, "country": "Italy", "timezone": "Europe/Rome"},
    "berlin": {"name": "Berlin", "latitude": 52.5200, "longitude": 13.4050, "country": "Germany", "timezone": "Europe/Berlin"},
    "munich": {"name": "Munich", "latitude": 48.1351, "longitude": 11.5820, "country": "Germany", "timezone": "Europe/Berlin"},
    "frankfurt": {"name": "Frankfurt", "latitude": 50.1109, "longitude": 8.6821, "country": "Germany", "timezone": "Europe/Berlin"},
    "hamburg": {"name": "Hamburg", "latitude": 53.5511, "longitude": 9.9937, "country": "Germany", "timezone": "Europe/Berlin"},
    "madrid": {"name": "Madrid", "latitude": 40.4168, "longitude": -3.7038, "country": "Spain", "timezone": "Europe/Madrid"},
    "barcelona": {"name": "Barcelona", "latitude": 41.3874, "longitude": 2.1686, "country": "Spain", "timezone": "Europe/Madrid"},
    "lisbon": {"name": "Lisbon", "latitude": 38.7223, "longitude": -9.1393, "country": "Portugal", "timezone": "Europe/Lisbon"},
    "amsterdam": {"name": "Amsterdam", "latitude": 52.3676, "longitude": 4.9041, "country": "Netherlands", "timezone": "Europe/Amsterdam"},
    "brussels": {"name": "Brussels", "latitude": 50.8503, "longitude": 4.3517, "country": "Belgium", "timezone": "Europe/Brussels"},
    "vienna": {"name": "Vienna", "latitude": 48.2082, "longitude": 16.3738, "country": "Austria", "timezone": "Europe/Vienna"},
    "zurich": {"name": "Zurich", "latitude": 47.3769, "longitude": 8.5417, "country": "Switzerland", "timezone": "Europe/Zurich"},
    "geneva": {"name": "Geneva", "latitude": 46.2044, "longitude": 6.1432, "country": "Switzerland", "timezone": "Europe/Zurich"},
    "copenhagen": {"name": "Copenhagen", "latitude": 55.6761, "longitude": 12.5683, "country": "Denmark", "timezone": "Europe/Copenhagen"},
    "stockholm": {"name": "Stockholm", "latitude": 59.3293, "longitude": 18.0686, "country": "Sweden", "timezone": "Europe/Stockholm"},
    "oslo": {"name": "Oslo", "latitude": 59.9139, "longitude": 10.7522, "country": "Norway", "timezone": "Europe/Oslo"},
    "helsinki": {"name": "Helsinki", "latitude": 60.1699, "longitude": 24.9384, "country": "Finland", "timezone": "Europe/Helsinki"},
    "reykjavik": {"name": "Reykjavik", "latitude": 64.1466, "longitude": -21.9426, "country": "Iceland", "timezone": "Atlantic/Reykjavik"},
    "prague": {"name": "Prague", "latitude": 50.0755, "longitude": 14.4378, "country": "Czechia", "timezone": "Europe/Prague"},
    "warsaw": {"name": "Warsaw", "latitude": 52.2297, "longitude": 21.0122, "country": "Poland", "timezone": "Europe/Warsaw"},
    "budapest": {"name": "Budapest", "latitude": 47.4979, "longitude": 19.0402, "country": "Hungary", "timezone": "Europe/Budapest"},
    "athens": {"name": "Athens", "latitude": 37.9838, "longitude": 23.7275, "country": "Greece", "timezone": "Europe/Athens"},
    "istanbul": {"name": "Istanbul", "latitude": 41.0082, "longitude": 28.9784, "country": "Turkey", "timezone": "Europe/Istanbul"},
    "antalya": {"name": "Antalya", "latitude": 36.8969, "longitude": 30.7133, "country": "Turkey", "timezone": "Europe/Istanbul"},
    "baku": {"name": "Baku", "latitude": 40.4093, "longitude": 49.8671, "country": "Azerbaijan", "timezone": "Asia/Baku"},
    "tbilisi": {"name": "Tbilisi", "latitude": 41.7151, "longitude": 44.8271, "country": "Georgia", "timezone": "Asia/Tbilisi"},
    "yerevan": {"name": "Yerevan", "latitude": 40.1792, "longitude": 44.4991, "country": "Armenia", "timezone": "Asia/Yerevan"},
    "nice": {"name": "Nice", "latitude": 43.7102, "longitude": 7.2620, "country": "France", "timezone": "Europe/Paris"},
    "monaco": {"name": "Monaco", "latitude": 43.7384, "longitude": 7.4246, "country": "Monaco", "timezone": "Europe/Monaco"},
    "dubai": {"name": "Dubai", "latitude": 25.2048, "longitude": 55.2708, "country": "United Arab Emirates", "timezone": "Asia/Dubai"},
    "doha": {"name": "Doha", "latitude": 25.2854, "longitude": 51.5310, "country": "Qatar", "timezone": "Asia/Qatar"},
    "riyadh": {"name": "Riyadh", "latitude": 24.7136, "longitude": 46.6753, "country": "Saudi Arabia", "timezone": "Asia/Riyadh"},
    "cairo": {"name": "Cairo", "latitude": 30.0444, "longitude": 31.2357, "country": "Egypt", "timezone": "Africa/Cairo"},
    "tokyo": {"name": "Tokyo", "latitude": 35.6762, "longitude": 139.6503, "country": "Japan", "timezone": "Asia/Tokyo"},
    "kyoto": {"name": "Kyoto", "latitude": 35.0116, "longitude": 135.7681, "country": "Japan", "timezone": "Asia/Tokyo"},
    "seoul": {"name": "Seoul", "latitude": 37.5665, "longitude": 126.9780, "country": "South Korea", "timezone": "Asia/Seoul"},
    "singapore": {"name": "Singapore", "latitude": 1.3521, "longitude": 103.8198, "country": "Singapore", "timezone": "Asia/Singapore"},
    "hong kong": {"name": "Hong Kong", "latitude": 22.3193, "longitude": 114.1694, "country": "Hong Kong", "timezone": "Asia/Hong_Kong"},
    "bangkok": {"name": "Bangkok", "latitude": 13.7563, "longitude": 100.5018, "country": "Thailand", "timezone": "Asia/Bangkok"},
    "mumbai": {"name": "Mumbai", "latitude": 19.0760, "longitude": 72.8777, "country": "India", "timezone": "Asia/Kolkata"},
    "delhi": {"name": "Delhi", "latitude": 28.6139, "longitude": 77.2090, "country": "India", "timezone": "Asia/Kolkata"},
    "beijing": {"name": "Beijing", "latitude": 39.9042, "longitude": 116.4074, "country": "China", "timezone": "Asia/Shanghai"},
    "shanghai": {"name": "Shanghai", "latitude": 31.2304, "longitude": 121.4737, "country": "China", "timezone": "Asia/Shanghai"},
    "taipei": {"name": "Taipei", "latitude": 25.0330, "longitude": 121.5654, "country": "Taiwan", "timezone": "Asia/Taipei"},
    "sydney": {"name": "Sydney", "latitude": -33.8688, "longitude": 151.2093, "country": "Australia", "timezone": "Australia/Sydney"},
    "melbourne": {"name": "Melbourne", "latitude": -37.8136, "longitude": 144.9631, "country": "Australia", "timezone": "Australia/Melbourne"},
    "auckland": {"name": "Auckland", "latitude": -36.8485, "longitude": 174.7633, "country": "New Zealand", "timezone": "Pacific/Auckland"},
    "buenos aires": {"name": "Buenos Aires", "latitude": -34.6037, "longitude": -58.3816, "country": "Argentina", "timezone": "America/Argentina/Buenos_Aires"},
}

WEEKDAY_INDEX: Dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTH_INDEX: Dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _format_utc_iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class WeatherConfig:
    """Environment-driven configuration for Weather Context integration."""

    base_url: str = WeatherAgent.BASE_URL
    geocoding_url: str = WeatherAgent.GEOCODING_URL
    api_key: Optional[str] = None
    timeout_seconds: float = 10.0
    cache_ttl_seconds: int = 600
    cache_max_size: int = 128
    max_forecast_days: int = 16
    timezone: str = "auto"
    default_mode: str = "current"
    default_location: Optional[str] = None
    default_latitude: Optional[float] = None
    default_longitude: Optional[float] = None

    @classmethod
    def from_env(cls) -> "WeatherConfig":
        def _opt_str(name: str) -> Optional[str]:
            val = os.environ.get(name)
            return val.strip() if val and val.strip() else None

        def _opt_float(name: str) -> Optional[float]:
            val = _opt_str(name)
            return float(val) if val is not None else None

        return cls(
            base_url=_opt_str("WEATHER_API_BASE_URL") or WeatherAgent.BASE_URL,
            geocoding_url=_opt_str("WEATHER_GEOCODING_URL") or WeatherAgent.GEOCODING_URL,
            api_key=_opt_str("WEATHER_API_KEY"),
            timeout_seconds=float(_opt_str("WEATHER_API_TIMEOUT") or 10.0),
            cache_ttl_seconds=int(_opt_str("WEATHER_CACHE_TTL_SECONDS") or 600),
            cache_max_size=int(_opt_str("WEATHER_CACHE_MAX_SIZE") or 128),
            max_forecast_days=int(_opt_str("WEATHER_MAX_FORECAST_DAYS") or 16),
            timezone=_opt_str("WEATHER_TIMEZONE") or "auto",
            default_mode=_opt_str("WEATHER_DEFAULT_MODE") or "current",
            default_location=_opt_str("WEATHER_DEFAULT_LOCATION"),
            default_latitude=_opt_float("WEATHER_DEFAULT_LATITUDE"),
            default_longitude=_opt_float("WEATHER_DEFAULT_LONGITUDE"),
        )


@dataclass
class _CacheEntry:
    context: WeatherContext
    fetched_at: datetime.datetime
    expires_at: datetime.datetime


class WeatherCache:
    """
    Small, bounded, thread-safe in-memory TTL cache for validated weather contexts.
    Never returns expired/stale entries as live weather.
    """

    def __init__(
        self,
        ttl_seconds: int = 600,
        max_size: int = 128,
        clock: Callable[[], datetime.datetime] = _utc_now,
    ):
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.max_size = max(1, int(max_size))
        self.clock = clock
        self._store: Dict[Tuple[Any, ...], _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: Tuple[Any, ...]) -> Optional[WeatherContext]:
        if self.ttl_seconds <= 0:
            return None
        now = self.clock()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if now >= entry.expires_at:
                # Expired / stale entry: evict immediately and never return as live weather
                del self._store[key]
                return None
            cached_copy = entry.context.model_copy(deep=True)
            cached_copy.cached = True
            cached_copy.fetched_at = _format_utc_iso(entry.fetched_at)
            cached_copy.cache_expires_at = _format_utc_iso(entry.expires_at)
            return cached_copy

    def set(self, key: Tuple[Any, ...], context: WeatherContext) -> Tuple[str, str]:
        now = self.clock()
        expires = now + datetime.timedelta(seconds=self.ttl_seconds)
        fetched_iso = _format_utc_iso(now)
        expires_iso = _format_utc_iso(expires)

        if self.ttl_seconds <= 0 or not context.available:
            return fetched_iso, expires_iso

        stored = context.model_copy(deep=True)
        stored.cached = False
        stored.fetched_at = fetched_iso
        stored.cache_expires_at = expires_iso

        with self._lock:
            # Evict expired entries first, then oldest entry if bounded size reached
            expired_keys = [k for k, v in self._store.items() if now >= v.expires_at]
            for k in expired_keys:
                del self._store[k]
            if len(self._store) >= self.max_size and key not in self._store:
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]
            self._store[key] = _CacheEntry(
                context=stored,
                fetched_at=now,
                expires_at=expires,
            )
        return fetched_iso, expires_iso

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


class LocationResolver:
    """
    Modular geographic location resolver enforcing strict priority order:
      1. Explicit geographic location extracted from the current user request
      2. Explicit location supplied via application settings / parameters / pluggable source
      3. Unavailable (`MissingLocationError`) — never invents a fallback city or guesses IP
    """

    def __init__(
        self,
        weather_agent: Optional[WeatherAgent] = None,
        config: Optional[WeatherConfig] = None,
        fallback_provider: Optional[Callable[[], Optional[Union[str, Tuple[float, float]]]]] = None,
    ):
        self.weather_agent = weather_agent
        self.config = config or WeatherConfig()
        self.fallback_provider = fallback_provider
        self._geocoded_cache: Dict[str, Dict[str, Any]] = {}

    def cache_geocoded_location(self, query: str, entry: Dict[str, Any]) -> None:
        key = (query or "").strip().lower()
        if key:
            if len(self._geocoded_cache) >= 256:
                self._geocoded_cache.pop(next(iter(self._geocoded_cache)))
            self._geocoded_cache[key] = dict(entry)

    @staticmethod
    def is_non_geographic_venue(value: Optional[str]) -> bool:
        if not value:
            return True
        return value.strip().lower() in NON_GEOGRAPHIC_VENUES

    def resolve(
        self,
        location: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        source: Literal["request", "settings", "coordinates"] = "request",
    ) -> ResolvedLocationModel:
        """Resolves an explicit coordinate pair or location name into validated coordinates."""
        if latitude is not None or longitude is not None:
            if latitude is None or longitude is None:
                raise InvalidLocationError("Both latitude and longitude must be provided together.")
            try:
                lat, lon = validate_coordinates(latitude, longitude)
            except InvalidCoordinatesError as exc:
                raise InvalidLocationError(str(exc)) from exc

            label = location.strip() if location and location.strip() else f"{lat:.4f}, {lon:.4f}"
            return ResolvedLocationModel(
                name=label,
                latitude=lat,
                longitude=lon,
                source="coordinates" if not (location and location.strip()) else source,
            )

        if location is None or not str(location).strip():
            raise MissingLocationError(
                "No geographic location was provided. Supply a city name or coordinates."
            )

        cleaned = str(location).strip()

        # Support coordinate strings formatted like "35.6892, 51.3890"
        coord_match = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$", cleaned)
        if coord_match:
            try:
                lat, lon = validate_coordinates(coord_match.group(1), coord_match.group(2))
            except InvalidCoordinatesError as exc:
                raise InvalidLocationError(str(exc)) from exc
            return ResolvedLocationModel(
                name=f"{lat:.4f}, {lon:.4f}",
                latitude=lat,
                longitude=lon,
                source="coordinates",
            )

        # Reject purely numeric / punctuation strings that are not valid place names
        if not re.search(r"[A-Za-z\u00C0-\u024F]", cleaned):
            raise InvalidLocationError(f"Location '{cleaned}' is not a valid geographic place name.")

        lower_clean = cleaned.lower()
        if lower_clean in NON_GEOGRAPHIC_VENUES:
            raise MissingLocationError(
                f"'{cleaned}' describes a venue setting rather than a geographic city or coordinate."
            )

        # 1. Check built-in deterministic city gazetteer (also handles "Boston, MA" -> "boston")
        candidates = [lower_clean]
        if "," in lower_clean:
            city_prefix = lower_clean.split(",", 1)[0].strip()
            if city_prefix:
                candidates.append(city_prefix)

        for cand in candidates:
            if cand in CITY_GAZETTEER:
                entry = CITY_GAZETTEER[cand]
                return ResolvedLocationModel(
                    name=entry["name"],
                    latitude=entry["latitude"],
                    longitude=entry["longitude"],
                    country=entry.get("country"),
                    timezone=entry.get("timezone"),
                    source=source,
                )
            if cand in self._geocoded_cache:
                entry = self._geocoded_cache[cand]
                return ResolvedLocationModel(
                    name=entry["name"],
                    latitude=entry["latitude"],
                    longitude=entry["longitude"],
                    country=entry.get("country"),
                    timezone=entry.get("timezone"),
                    source=source,
                )

        # 2. Fallback to Open-Meteo Geocoding API via WeatherAgent if available
        if self.weather_agent is not None and hasattr(self.weather_agent, "geocode_location"):
            geocoded = self.weather_agent.geocode_location(cleaned)
            if geocoded is not None:
                self.cache_geocoded_location(cleaned, geocoded)
                return ResolvedLocationModel(
                    name=geocoded["name"],
                    latitude=geocoded["latitude"],
                    longitude=geocoded["longitude"],
                    country=geocoded.get("country"),
                    timezone=geocoded.get("timezone"),
                    source=source,
                )

        raise InvalidLocationError(f"Could not resolve geographic location '{cleaned}'.")

    def resolve_for_request(
        self,
        structured_request: FashionRequestOutput,
        fallback_location: Optional[str] = None,
        fallback_latitude: Optional[float] = None,
        fallback_longitude: Optional[float] = None,
    ) -> ResolvedLocationModel:
        """
        Resolves the best location for a `FashionRequestOutput` following strict priority:
          1. Explicit geographic location in `structured_request.location`
          2. Explicit fallback parameter on the API call (`fallback_location` / coordinates)
          3. Configured application setting (`WeatherConfig` or `fallback_provider`)
          4. Raises `MissingLocationError`
        """
        # Priority 1: Explicit location inside the current user request
        req_loc = structured_request.location.value if structured_request.location else None
        if req_loc and not self.is_non_geographic_venue(req_loc):
            return self.resolve(location=req_loc, source="request")

        # Priority 2: Explicit application/request setting supplied alongside the call
        if fallback_latitude is not None or fallback_longitude is not None:
            return self.resolve(
                location=fallback_location,
                latitude=fallback_latitude,
                longitude=fallback_longitude,
                source="coordinates",
            )
        if fallback_location and fallback_location.strip():
            return self.resolve(location=fallback_location, source="settings")

        # Priority 3: Configured environment setting or modular provider hook (if any)
        if self.config.default_latitude is not None or self.config.default_longitude is not None:
            return self.resolve(
                location=self.config.default_location,
                latitude=self.config.default_latitude,
                longitude=self.config.default_longitude,
                source="settings",
            )
        if self.config.default_location:
            return self.resolve(location=self.config.default_location, source="settings")

        if self.fallback_provider is not None:
            provided = self.fallback_provider()
            if isinstance(provided, tuple) and len(provided) == 2:
                return self.resolve(latitude=provided[0], longitude=provided[1], source="settings")
            if isinstance(provided, str) and provided.strip():
                return self.resolve(location=provided, source="settings")

        raise MissingLocationError(
            "No location specified in the user request or application settings."
        )


def parse_forecast_target(
    date_or_time: Optional[Union[str, datetime.date, datetime.datetime]],
    reference_date: Optional[datetime.date] = None,
    default_mode: str = "current",
) -> Tuple[Literal["current", "forecast"], Optional[datetime.date], Optional[str]]:
    """
    Resolves an optional temporal expression or ISO date into `(mode, target_date, period)`.
    - Returns `("current", None, None)` when no date/time is specified (default behavior).
    - Returns `("forecast", date, optional_period)` when a date or sub-day window is specified.
    - Raises `UnsupportedForecastError` if an unrecognizable temporal string is supplied.
    """
    ref = reference_date or datetime.date.today()

    if date_or_time is None:
        return ("current", None, None)

    if isinstance(date_or_time, datetime.datetime):
        hour = date_or_time.hour
        period = (
            "morning" if 6 <= hour <= 11
            else ("afternoon" if 12 <= hour <= 17 else "evening")
        )
        return ("forecast", date_or_time.date(), period)

    if isinstance(date_or_time, datetime.date):
        return ("forecast", date_or_time, None)

    raw = str(date_or_time).strip()
    if not raw:
        return ("current", None, None)

    lower = raw.lower()
    if lower in ("now", "right now", "current", "currently"):
        return ("current", None, None)

    # Extract optional time-of-day window token
    period: Optional[str] = None
    if re.search(r"\bmorning\b", lower):
        period = "morning"
    elif re.search(r"\bafternoon\b", lower):
        period = "afternoon"
    elif re.search(r"\b(?:evening|tonight)\b", lower):
        period = "evening"
    elif re.search(r"\bnight\b", lower):
        period = "night"

    # 1. Explicit ISO datetime or ISO date (e.g. "2026-10-24", "2026-10-24 morning", "2026-10-24T15:00")
    iso_dt_match = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})(?:[T\s]+(\d{1,2}):(\d{2})(?::\d{2})?)?(?:\s+(morning|afternoon|evening|night))?$",
        lower,
    )
    if iso_dt_match:
        try:
            parsed_date = datetime.date(
                int(iso_dt_match.group(1)),
                int(iso_dt_match.group(2)),
                int(iso_dt_match.group(3)),
            )
        except ValueError as exc:
            raise UnsupportedForecastError(f"Invalid calendar date '{raw}'.") from exc

        if iso_dt_match.group(4) is not None and period is None:
            hr = int(iso_dt_match.group(4))
            period = (
                "morning" if hr < 12 else ("afternoon" if hr < 18 else "evening")
            )
        return ("forecast", parsed_date, period)

    # 2. Relative natural-language phrases
    if re.search(r"\btomorrow\b", lower):
        return ("forecast", ref + datetime.timedelta(days=1), period)

    if re.search(r"\b(?:today|tonight|this\s+(?:morning|afternoon|evening|night))\b", lower):
        return ("forecast", ref, period)

    if re.search(r"\bnext\s+weekend\b", lower):
        days_until_sat = (5 - ref.weekday()) % 7
        return ("forecast", ref + datetime.timedelta(days=days_until_sat + 7), period)

    if re.search(r"\bthis\s+weekend\b|\bweekend\b", lower):
        days_until_sat = (5 - ref.weekday()) % 7
        return ("forecast", ref + datetime.timedelta(days=days_until_sat), period)

    if re.search(r"\bnext\s+week\b", lower):
        return ("forecast", ref + datetime.timedelta(days=7), period)

    if re.search(r"\bnext\s+month\b", lower):
        return ("forecast", ref + datetime.timedelta(days=30), period)

    if re.search(r"\bnext\s+year\b", lower):
        return ("forecast", ref + datetime.timedelta(days=365), period)

    rel_in_match = re.search(r"\bin\s+(\d+)\s+(day|days|week|weeks|month|months)\b", lower)
    if rel_in_match:
        count = int(rel_in_match.group(1))
        unit = rel_in_match.group(2)
        mult = 1 if unit.startswith("day") else (7 if unit.startswith("week") else 30)
        return ("forecast", ref + datetime.timedelta(days=count * mult), period)

    # 3. Named weekdays (e.g. "Saturday", "this Saturday", "next Friday morning")
    for day_name, target_idx in WEEKDAY_INDEX.items():
        m_day = re.search(rf"\b(next\s+|this\s+)?{day_name}\b", lower)
        if m_day:
            delta = (target_idx - ref.weekday()) % 7
            if m_day.group(1) and "next" in m_day.group(1) and delta == 0:
                delta = 7
            return ("forecast", ref + datetime.timedelta(days=delta), period)

    # 4. Month + Day format (e.g., "October 25" or "November 20, 2026")
    month_match = re.search(
        r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
        lower,
    )
    if month_match and month_match.group(1) in MONTH_INDEX:
        month_num = MONTH_INDEX[month_match.group(1)]
        day_num = int(month_match.group(2))
        year_num = int(month_match.group(3)) if month_match.group(3) else ref.year
        try:
            parsed_date = datetime.date(year_num, month_num, day_num)
        except ValueError as exc:
            raise UnsupportedForecastError(f"Invalid calendar date '{raw}'.") from exc
        return ("forecast", parsed_date, period)

    raise UnsupportedForecastError(
        f"Unsupported or unrecognized forecast date/time specification '{raw}'."
    )


class WeatherContextService:
    """
    Application service bridging the Fashion AI interaction pipeline with `WeatherAgent`.
    Exposes `get_weather_context(location, date_or_time, ...)` with validation,
    caching, forecast selection, and explicit unavailable/error states.
    """

    def __init__(
        self,
        weather_agent: Optional[Any] = None,
        config: Optional[WeatherConfig] = None,
        cache: Optional[WeatherCache] = None,
        location_resolver: Optional[LocationResolver] = None,
        reference_date: Optional[datetime.date] = None,
    ):
        self.config = config or WeatherConfig.from_env()
        self.weather_agent = weather_agent or WeatherAgent(
            base_url=self.config.base_url,
            geocoding_url=self.config.geocoding_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
            max_forecast_days=self.config.max_forecast_days,
        )
        self.cache = (
            cache
            if cache is not None
            else WeatherCache(
                ttl_seconds=self.config.cache_ttl_seconds,
                max_size=self.config.cache_max_size,
            )
        )
        self.location_resolver = location_resolver or LocationResolver(
            weather_agent=self.weather_agent,
            config=self.config,
        )
        self.reference_date = reference_date

    def _unavailable(
        self,
        status: WeatherStatusLiteral,
        message: str,
        mode: Optional[Literal["current", "forecast"]] = None,
        location: Optional[ResolvedLocationModel] = None,
        forecast_for: Optional[str] = None,
    ) -> WeatherContext:
        return WeatherContext(
            available=False,
            status=status,
            mode=mode,
            message=message,
            location=location,
            forecast_for=forecast_for,
            source="open-meteo",
            cached=False,
        )

    def _classify_exception(self, exc: Exception) -> Tuple[WeatherStatusLiteral, str]:
        if isinstance(exc, InvalidLocationError) or isinstance(exc, InvalidCoordinatesError):
            return ("invalid_location", str(exc))
        if isinstance(exc, MissingLocationError):
            return ("missing_location", str(exc))
        if isinstance(exc, UnsupportedForecastError):
            return ("unsupported_forecast_date", str(exc))
        if isinstance(exc, (WeatherTimeoutError, requests.exceptions.Timeout)):
            return ("timeout", "Weather provider request timed out.")
        if isinstance(exc, WeatherRateLimitError):
            return ("rate_limited", str(exc))
        if isinstance(exc, WeatherAuthError):
            return ("invalid_credentials", "Weather provider authentication failed.")
        if isinstance(exc, WeatherMissingFieldsError) or isinstance(exc, KeyError):
            return ("missing_weather_fields", f"Required weather fields missing: {exc}")
        if isinstance(exc, (WeatherResponseError, ValueError, TypeError)):
            return ("invalid_response", f"Malformed weather provider response: {exc}")
        if isinstance(exc, (WeatherNetworkError, requests.exceptions.RequestException)):
            if isinstance(exc, requests.exceptions.HTTPError) and getattr(exc, "response", None) is not None:
                code = exc.response.status_code
                if code in (401, 403):
                    return ("invalid_credentials", f"Weather provider rejected credentials (HTTP {code}).")
                if code == 429:
                    return ("rate_limited", "Weather provider rate limit exceeded (HTTP 429).")
            return ("network_error", "Unable to reach weather provider over the network.")
        if isinstance(exc, WeatherAgentError):
            return ("provider_error", str(exc))
        return ("provider_error", f"Unexpected weather integration error: {exc}")

    def get_weather_context(
        self,
        location: Optional[str] = None,
        date_or_time: Optional[Union[str, datetime.date, datetime.datetime]] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        location_source: Literal["request", "settings", "coordinates"] = "request",
    ) -> WeatherContext:
        """
        Retrieves validated `WeatherContext` for the given location and optional date/time.
        Never raises uncaught provider errors or returns fabricated fallback weather values.
        """
        # 1. Resolve target geographic location
        try:
            if location is None and latitude is None and longitude is None:
                # Allow configured application fallback if present; otherwise missing_location
                if (
                    self.config.default_latitude is not None
                    or self.config.default_longitude is not None
                    or self.config.default_location
                ):
                    resolved_loc = self.location_resolver.resolve(
                        location=self.config.default_location,
                        latitude=self.config.default_latitude,
                        longitude=self.config.default_longitude,
                        source="settings",
                    )
                else:
                    raise MissingLocationError(
                        "No location was supplied to retrieve weather context."
                    )
            else:
                resolved_loc = self.location_resolver.resolve(
                    location=location,
                    latitude=latitude,
                    longitude=longitude,
                    source=location_source,
                )
        except Exception as exc:
            status, msg = self._classify_exception(exc)
            logger.info("Weather location unavailable (%s): %s", status, msg)
            return self._unavailable(status=status, message=msg)

        return self._fetch_for_resolved_location(resolved_loc, date_or_time=date_or_time)

    def _fetch_for_resolved_location(
        self,
        resolved_loc: ResolvedLocationModel,
        date_or_time: Optional[Union[str, datetime.date, datetime.datetime]] = None,
    ) -> WeatherContext:
        ref_date = self.reference_date or datetime.date.today()

        # 2. Parse requested date / forecast window
        try:
            mode, target_date, period = parse_forecast_target(
                date_or_time=date_or_time,
                reference_date=ref_date,
                default_mode=self.config.default_mode,
            )
        except UnsupportedForecastError as exc:
            return self._unavailable(
                status="unsupported_forecast_date",
                message=str(exc),
                mode="forecast",
                location=resolved_loc,
                forecast_for=str(date_or_time) if date_or_time is not None else None,
            )

        forecast_label: Optional[str] = None
        if mode == "forecast" and target_date is not None:
            forecast_label = f"{target_date.isoformat()} {period}" if period else target_date.isoformat()

        # 3. Check fresh TTL cache before hitting network
        cache_key = (
            round(resolved_loc.latitude, 3),
            round(resolved_loc.longitude, 3),
            mode,
            forecast_label or "current",
        )
        cached_ctx = self.cache.get(cache_key)
        if cached_ctx is not None:
            # Preserve caller's current source metadata on the resolved location copy
            if cached_ctx.location is not None:
                cached_ctx.location.source = resolved_loc.source
            return cached_ctx

        # 4. Query WeatherAgent (current conditions vs forecast)
        tz_param = self.config.timezone or "auto"
        try:
            if mode == "forecast":
                assert target_date is not None
                if not hasattr(self.weather_agent, "get_forecast"):
                    return self._unavailable(
                        status="unsupported_forecast_date",
                        message="Configured weather agent supports current observations only, not forecasts.",
                        mode="forecast",
                        location=resolved_loc,
                        forecast_for=forecast_label,
                    )
                raw_data = self.weather_agent.get_forecast(
                    latitude=resolved_loc.latitude,
                    longitude=resolved_loc.longitude,
                    target_date=target_date,
                    period=period,
                    reference_date=ref_date,
                    timezone=tz_param,
                )
            else:
                if hasattr(self.weather_agent, "get_current_weather"):
                    raw_data = self.weather_agent.get_current_weather(
                        latitude=resolved_loc.latitude,
                        longitude=resolved_loc.longitude,
                        timezone=tz_param,
                    )
                else:
                    # Compatible with minimal duck-typed WeatherAgent implementing only get_weather(lat, lon)
                    legacy = self.weather_agent.get_weather(
                        latitude=resolved_loc.latitude,
                        longitude=resolved_loc.longitude,
                    )
                    if not isinstance(legacy, dict):
                        raise WeatherResponseError("WeatherAgent.get_weather() must return a dict.")
                    for req_key in ("temp", "humidity", "precipitation", "wind_speed"):
                        if req_key not in legacy or legacy[req_key] is None:
                            raise WeatherMissingFieldsError(f"Missing field '{req_key}' in get_weather() output.")
                    raw_data = {
                        "temp": float(legacy["temp"]),
                        "feels_like": None,
                        "humidity_ratio": float(legacy["humidity"]),
                        "precipitation_mm": None,
                        "precipitation_scaled_only": float(legacy["precipitation"]),
                        "precipitation_probability": None,
                        "wind_speed": float(legacy["wind_speed"]),
                        "condition": None,
                        "observed_at": None,
                        "timezone": None,
                        "units": {"temperature": "C", "wind_speed": "km/h", "precipitation": "scaled_ratio"},
                        "agent_metrics": {
                            "temp": float(legacy["temp"]),
                            "humidity": float(legacy["humidity"]),
                            "precipitation": float(legacy["precipitation"]),
                            "wind_speed": float(legacy["wind_speed"]),
                        },
                    }
        except Exception as exc:
            status, msg = self._classify_exception(exc)
            logger.warning("Weather retrieval failed (%s): %s", status, msg)
            return self._unavailable(
                status=status,
                message=msg,
                mode=mode,
                location=resolved_loc,
                forecast_for=forecast_label,
            )

        # 5. Construct validated WeatherContext strictly from actual provider fields
        return self._finalize_and_cache_context(
            raw_data=raw_data,
            resolved_loc=resolved_loc,
            mode=mode,
            forecast_label=forecast_label,
            cache_key=cache_key,
        )

    def _finalize_and_cache_context(
        self,
        raw_data: Dict[str, Any],
        resolved_loc: ResolvedLocationModel,
        mode: Literal["current", "forecast"],
        forecast_label: Optional[str],
        cache_key: Tuple[Any, ...],
    ) -> WeatherContext:
        units = raw_data.get("units", {})
        temp_unit = units.get("temperature", "C")
        wind_unit = units.get("wind_speed", "km/h")
        precip_unit = units.get("precipitation", "mm")

        loc_out = resolved_loc.model_copy(deep=True)
        if raw_data.get("timezone") and not loc_out.timezone:
            loc_out.timezone = raw_data["timezone"]

        temp_range = None
        if raw_data.get("temp_min") is not None and raw_data.get("temp_max") is not None:
            temp_range = TemperatureRange(
                min=raw_data["temp_min"],
                max=raw_data["temp_max"],
                unit=temp_unit,
            )

        feels_like_model = (
            MeasurementValue(value=raw_data["feels_like"], unit=temp_unit)
            if raw_data.get("feels_like") is not None
            else None
        )
        humidity_model = (
            MeasurementValue(value=raw_data["humidity_ratio"], unit="ratio")
            if raw_data.get("humidity_ratio") is not None
            else None
        )

        if raw_data.get("precipitation_mm") is not None:
            precip_model: Optional[MeasurementValue] = MeasurementValue(
                value=raw_data["precipitation_mm"],
                unit=precip_unit,
            )
        elif raw_data.get("precipitation_scaled_only") is not None:
            precip_model = MeasurementValue(
                value=raw_data["precipitation_scaled_only"],
                unit="scaled_ratio",
            )
        else:
            precip_model = None

        agent_metrics_model = (
            WeatherAgentMetrics(**raw_data["agent_metrics"])
            if isinstance(raw_data.get("agent_metrics"), dict)
            else None
        )

        context = WeatherContext(
            available=True,
            status="ok",
            mode=mode,
            message=None,
            location=loc_out,
            observed_at=raw_data.get("observed_at"),
            forecast_for=raw_data.get("forecast_for") or forecast_label,
            temperature=MeasurementValue(value=raw_data["temp"], unit=temp_unit),
            temperature_range=temp_range,
            feels_like=feels_like_model,
            condition=raw_data.get("condition"),
            humidity=humidity_model,
            precipitation=precip_model,
            precipitation_probability=raw_data.get("precipitation_probability"),
            wind_speed=MeasurementValue(value=raw_data["wind_speed"], unit=wind_unit),
            agent_metrics=agent_metrics_model,
            source="open-meteo",
            cached=False,
        )

        fetched_iso, expires_iso = self.cache.set(cache_key, context)
        context.fetched_at = fetched_iso
        context.cache_expires_at = expires_iso
        return context

    def resolve_from_provider_payload(
        self,
        location: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        location_source: Literal["request", "settings", "coordinates"] = "request",
        date_or_time: Optional[Union[str, datetime.date, datetime.datetime]] = None,
        geocoding_payload: Optional[Dict[str, Any]] = None,
        provider_payload: Optional[Dict[str, Any]] = None,
    ) -> WeatherContext:
        """
        Validates raw Open-Meteo geocoding/weather JSON payloads using `WeatherAgent`'s
        canonical schema validators, populates `WeatherCache`, and returns `WeatherContext`.
        Used seamlessly when sandboxed backend containers delegate public HTTPS transport.
        """
        ref_date = self.reference_date or datetime.date.today()

        # 1. Resolve target location locally or from Open-Meteo geocoding payload
        resolved_loc: Optional[ResolvedLocationModel] = None
        try:
            if latitude is not None and longitude is not None:
                resolved_loc = self.location_resolver.resolve(
                    location=location,
                    latitude=latitude,
                    longitude=longitude,
                    source=location_source,
                )
            elif geocoding_payload is not None and hasattr(self.weather_agent, "parse_geocoding_response"):
                geo = self.weather_agent.parse_geocoding_response(
                    geocoding_payload,
                    fallback_name=location or "",
                )
                if geo is None:
                    raise InvalidLocationError(f"Could not resolve geographic location '{location}'.")
                if location:
                    self.location_resolver.cache_geocoded_location(location, geo)
                resolved_loc = ResolvedLocationModel(
                    name=geo["name"],
                    latitude=geo["latitude"],
                    longitude=geo["longitude"],
                    country=geo.get("country"),
                    timezone=geo.get("timezone"),
                    source=location_source,
                )
            else:
                resolved_loc = self.location_resolver.resolve(
                    location=location,
                    source=location_source,
                )
        except Exception as exc:
            status, msg = self._classify_exception(exc)
            return self._unavailable(status=status, message=msg)

        # 2. Validate forecast date/period window
        try:
            mode, target_date, period = parse_forecast_target(
                date_or_time=date_or_time,
                reference_date=ref_date,
                default_mode=self.config.default_mode,
            )
            if mode == "forecast" and target_date is not None and hasattr(
                self.weather_agent, "validate_forecast_window"
            ):
                self.weather_agent.validate_forecast_window(
                    target_date=target_date,
                    period=period,
                    reference_date=ref_date,
                )
        except Exception as exc:
            status, msg = self._classify_exception(exc)
            return self._unavailable(
                status=status,
                message=msg,
                mode="forecast",
                location=resolved_loc,
                forecast_for=str(date_or_time) if date_or_time is not None else None,
            )

        forecast_label = (
            f"{target_date.isoformat()} {period}"
            if (mode == "forecast" and target_date is not None and period)
            else (target_date.isoformat() if (mode == "forecast" and target_date is not None) else None)
        )

        if provider_payload is None:
            return self._unavailable(
                status="network_error",
                message="Unable to reach weather provider over the network.",
                mode=mode,
                location=resolved_loc,
                forecast_for=forecast_label,
            )

        # 3. Validate & parse provider JSON strictly via WeatherAgent
        try:
            if mode == "forecast":
                assert target_date is not None
                raw_data = self.weather_agent.parse_forecast_response(
                    provider_payload,
                    target_date=target_date,
                    period=period,
                )
            else:
                raw_data = self.weather_agent.parse_current_response(provider_payload)
        except Exception as exc:
            status, msg = self._classify_exception(exc)
            return self._unavailable(
                status=status,
                message=msg,
                mode=mode,
                location=resolved_loc,
                forecast_for=forecast_label,
            )

        cache_key = (
            round(resolved_loc.latitude, 3),
            round(resolved_loc.longitude, 3),
            mode,
            forecast_label or "current",
        )
        return self._finalize_and_cache_context(
            raw_data=raw_data,
            resolved_loc=resolved_loc,
            mode=mode,
            forecast_label=forecast_label,
            cache_key=cache_key,
        )


class ContextIntegrator:
    """
    Context Aggregation Layer combining:
      1. `FashionRequestOutput` (user request features from voice or typed input)
      2. `WeatherContext` (independent environmental context from `WeatherContextService`)
    into a validated `RecommendationContext` without mutating user preferences or transcripts.
    """

    def __init__(self, weather_service: WeatherContextService):
        self.weather_service = weather_service

    def build_context(
        self,
        structured_request: FashionRequestOutput,
        fallback_location: Optional[str] = None,
        fallback_latitude: Optional[float] = None,
        fallback_longitude: Optional[float] = None,
    ) -> RecommendationContext:
        # Read temporal target from structured request without modifying structured_request
        requested_time: Optional[str] = None
        if structured_request.time and structured_request.time.source == "explicit":
            requested_time = structured_request.time.resolved or structured_request.time.expression

        try:
            resolved_loc = self.weather_service.location_resolver.resolve_for_request(
                structured_request=structured_request,
                fallback_location=fallback_location,
                fallback_latitude=fallback_latitude,
                fallback_longitude=fallback_longitude,
            )
            weather_ctx = self.weather_service._fetch_for_resolved_location(
                resolved_loc=resolved_loc,
                date_or_time=requested_time,
            )
        except Exception as exc:
            status, msg = self.weather_service._classify_exception(exc)
            weather_ctx = self.weather_service._unavailable(
                status=status,
                message=msg,
                mode="forecast" if requested_time else None,
                forecast_for=requested_time,
            )

        return RecommendationContext(
            request_context=structured_request.model_copy(deep=True),
            weather_context=weather_ctx,
        )


def get_weather_context(
    location: Optional[str] = None,
    date_or_time: Optional[Union[str, datetime.date, datetime.datetime]] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    service: Optional[WeatherContextService] = None,
) -> WeatherContext:
    """
    Convenience functional entrypoint for retrieving validated environmental weather context.
    """
    active_service = service or WeatherContextService()
    return active_service.get_weather_context(
        location=location,
        date_or_time=date_or_time,
        latitude=latitude,
        longitude=longitude,
    )
