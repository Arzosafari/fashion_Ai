# agents/weather_agent.py

import datetime
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import requests


class WeatherAgentError(Exception):
    """Base exception for WeatherAgent failures."""


class InvalidCoordinatesError(WeatherAgentError):
    """Raised when latitude or longitude values are non-numeric or out of range."""


class UnsupportedForecastError(WeatherAgentError):
    """Raised when a requested forecast date/period is outside provider bounds."""


class WeatherTimeoutError(WeatherAgentError):
    """Raised when the weather provider request times out."""


class WeatherNetworkError(WeatherAgentError):
    """Raised when a network/connection failure occurs contacting the provider."""


class WeatherRateLimitError(WeatherAgentError):
    """Raised when the weather provider returns HTTP 429 rate limiting."""


class WeatherAuthError(WeatherAgentError):
    """Raised when API credentials are rejected (HTTP 401/403)."""


class WeatherResponseError(WeatherAgentError):
    """Raised when the provider response is malformed JSON or has invalid field types."""


class WeatherMissingFieldsError(WeatherAgentError):
    """Raised when required weather observation/forecast fields are missing or null."""


# Standard WMO Weather interpretation codes used by Open-Meteo
WMO_WEATHER_CODES: Dict[int, str] = {
    0: "clear_sky",
    1: "mainly_clear",
    2: "partly_cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing_rime_fog",
    51: "light_drizzle",
    53: "moderate_drizzle",
    55: "dense_drizzle",
    56: "light_freezing_drizzle",
    57: "dense_freezing_drizzle",
    61: "light_rain",
    63: "moderate_rain",
    65: "heavy_rain",
    66: "light_freezing_rain",
    67: "heavy_freezing_rain",
    71: "light_snow",
    73: "moderate_snow",
    75: "heavy_snow",
    77: "snow_grains",
    80: "light_rain_showers",
    81: "moderate_rain_showers",
    82: "violent_rain_showers",
    85: "light_snow_showers",
    86: "heavy_snow_showers",
    95: "thunderstorm",
    96: "thunderstorm_with_light_hail",
    99: "thunderstorm_with_heavy_hail",
}

PERIOD_HOUR_RANGES: Dict[str, Tuple[int, int]] = {
    "morning": (8, 11),
    "afternoon": (12, 17),
    "evening": (18, 21),
    "night": (20, 23),
}


def validate_coordinates(latitude: Any, longitude: Any) -> Tuple[float, float]:
    """Validates geographic coordinates within WGS-84 bounds."""
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise InvalidCoordinatesError("Latitude and longitude must be numbers, not booleans.")
    if latitude is None or longitude is None:
        raise InvalidCoordinatesError("Latitude and longitude cannot be None.")
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise InvalidCoordinatesError(
            f"Latitude and longitude must be numeric values, got ({latitude!r}, {longitude!r})."
        ) from exc

    if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
        raise InvalidCoordinatesError("Latitude and longitude must be finite numbers.")
    if not (-90.0 <= lat <= 90.0):
        raise InvalidCoordinatesError(f"Latitude {lat} is out of valid range [-90.0, 90.0].")
    if not (-180.0 <= lon <= 180.0):
        raise InvalidCoordinatesError(f"Longitude {lon} is out of valid range [-180.0, 180.0].")
    return lat, lon


def _normalize_temp_unit(raw_unit: Optional[str]) -> str:
    if not raw_unit:
        return "C"
    cleaned = raw_unit.replace("°", "").strip()
    return cleaned or "C"


def _to_finite_float(value: Any, field_name: str) -> float:
    if value is None:
        raise WeatherMissingFieldsError(f"Required weather field '{field_name}' is null.")
    if isinstance(value, bool):
        raise WeatherResponseError(f"Weather field '{field_name}' had invalid boolean type.")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherResponseError(
            f"Weather field '{field_name}' could not be parsed as float: {value!r}"
        ) from exc
    if math.isnan(num) or math.isinf(num):
        raise WeatherResponseError(f"Weather field '{field_name}' is non-finite: {num!r}")
    return num


def _decode_wmo_condition(raw_code: Any) -> Optional[str]:
    if raw_code is None or isinstance(raw_code, bool):
        return None
    try:
        code = int(raw_code)
    except (TypeError, ValueError):
        return None
    return WMO_WEATHER_CODES.get(code, f"wmo_code_{code}")


class WeatherAgent:

    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    MAX_FORECAST_DAYS = 16

    def __init__(
        self,
        base_url: Optional[str] = None,
        geocoding_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_forecast_days: Optional[int] = None,
    ):
        self.base_url = (
            base_url
            or os.environ.get("WEATHER_API_BASE_URL")
            or self.BASE_URL
        )
        self.geocoding_url = (
            geocoding_url
            or os.environ.get("WEATHER_GEOCODING_URL")
            or self.GEOCODING_URL
        )
        self.api_key = api_key if api_key is not None else os.environ.get("WEATHER_API_KEY")
        env_timeout = os.environ.get("WEATHER_API_TIMEOUT")
        self.timeout = (
            float(timeout)
            if timeout is not None
            else (float(env_timeout) if env_timeout else 15.0)
        )
        env_max_days = os.environ.get("WEATHER_MAX_FORECAST_DAYS")
        self.max_forecast_days = (
            int(max_forecast_days)
            if max_forecast_days is not None
            else (int(env_max_days) if env_max_days else self.MAX_FORECAST_DAYS)
        )

    def _with_auth(self, params: Dict[str, Any]) -> Dict[str, Any]:
        final_params = dict(params)
        if self.api_key:
            final_params["apikey"] = self.api_key
        return final_params

    def _validate_provider_envelope(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise WeatherResponseError("Weather provider returned unexpected top-level JSON structure.")

        if data.get("error") is True:
            reason = str(data.get("reason", "Unknown provider error"))
            if "api key" in reason.lower() or "apikey" in reason.lower():
                raise WeatherAuthError(f"Weather provider reported invalid API credentials: {reason}")
            raise WeatherAgentError(f"Weather provider error: {reason}")

        return data

    def _perform_request(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Executes an HTTP GET request against Open-Meteo with structured error classification."""
        try:
            response = requests.get(
                url,
                params=self._with_auth(params),
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise WeatherTimeoutError("Weather provider request timed out.") from exc
        except requests.exceptions.RequestException as exc:
            raise WeatherNetworkError("Network failure while contacting weather provider.") from exc

        status_code = getattr(response, "status_code", 200)
        if status_code in (401, 403):
            raise WeatherAuthError(f"Weather provider rejected credentials (HTTP {status_code}).")
        if status_code == 429:
            raise WeatherRateLimitError("Weather provider rate limit exceeded (HTTP 429).")
        if status_code >= 400:
            body_reason = ""
            try:
                err_payload = response.json()
                if isinstance(err_payload, dict):
                    body_reason = str(err_payload.get("reason", ""))
            except Exception:
                body_reason = ""
            if "api key" in body_reason.lower() or "apikey" in body_reason.lower() or "unauthorized" in body_reason.lower():
                raise WeatherAuthError("Weather provider reported invalid API key.")
            raise WeatherAgentError(
                f"Weather provider returned HTTP {status_code}"
                + (f": {body_reason}" if body_reason else ".")
            )

        try:
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as exc:
            raise WeatherAgentError(f"Weather provider HTTP error: {exc}") from exc
        except ValueError as exc:
            raise WeatherResponseError("Weather provider returned malformed non-JSON payload.") from exc

        return self._validate_provider_envelope(data)

    def get_weather(
        self,
        latitude: float,
        longitude: float
    ) -> dict:
        """
        Original WeatherAgent interface preserved for backward compatibility.
        Returns normalized current weather metrics for (latitude, longitude).
        """
        params = self._with_auth({
            "latitude": latitude,
            "longitude": longitude,
            "current": [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "wind_speed_10m"
            ]
        })

        response = requests.get(
            self.base_url,
            params=params,
            timeout=self.timeout
        )

        response.raise_for_status()

        data = response.json()

        current = data["current"]

        return {
            "temp": float(current["temperature_2m"]),
            "humidity": float(current["relative_humidity_2m"]) / 100.0,
            "precipitation": min(
                float(current["precipitation"]),
                100.0
            ) / 100.0,
            "wind_speed": float(current["wind_speed_10m"])
        }

    def parse_current_response(self, raw_payload: Any) -> Dict[str, Any]:
        """Validates and normalizes a raw Open-Meteo current-conditions JSON payload."""
        data = self._validate_provider_envelope(raw_payload)
        current = data.get("current")
        if not isinstance(current, dict):
            raise WeatherMissingFieldsError("Provider response missing 'current' weather block.")

        required_fields = (
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
        )
        missing = [f for f in required_fields if f not in current or current[f] is None]
        if missing:
            raise WeatherMissingFieldsError(
                f"Provider response missing required current weather fields: {', '.join(missing)}"
            )

        temp_val = _to_finite_float(current["temperature_2m"], "temperature_2m")
        humidity_pct = _to_finite_float(current["relative_humidity_2m"], "relative_humidity_2m")
        precip_mm = _to_finite_float(current["precipitation"], "precipitation")
        wind_val = _to_finite_float(current["wind_speed_10m"], "wind_speed_10m")

        feels_like_val: Optional[float] = None
        if current.get("apparent_temperature") is not None:
            feels_like_val = _to_finite_float(current["apparent_temperature"], "apparent_temperature")

        units_block = data.get("current_units") if isinstance(data.get("current_units"), dict) else {}
        temp_unit = _normalize_temp_unit(units_block.get("temperature_2m"))
        wind_unit = str(units_block.get("wind_speed_10m") or "km/h")
        precip_unit = str(units_block.get("precipitation") or "mm")

        humidity_ratio = humidity_pct / 100.0
        precip_scaled = min(precip_mm, 100.0) / 100.0

        observed_at = current.get("time")
        if observed_at is not None and not isinstance(observed_at, str):
            observed_at = str(observed_at)

        resolved_tz = data.get("timezone") if isinstance(data.get("timezone"), str) else None

        return {
            "temp": temp_val,
            "feels_like": feels_like_val,
            "humidity_ratio": round(humidity_ratio, 4),
            "precipitation_mm": round(precip_mm, 3),
            "precipitation_probability": None,
            "wind_speed": wind_val,
            "condition": _decode_wmo_condition(current.get("weather_code")),
            "observed_at": observed_at,
            "timezone": resolved_tz,
            "units": {
                "temperature": temp_unit,
                "wind_speed": wind_unit,
                "precipitation": precip_unit,
            },
            "agent_metrics": {
                "temp": temp_val,
                "humidity": humidity_ratio,
                "precipitation": precip_scaled,
                "wind_speed": wind_val,
            },
        }

    def get_current_weather(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
    ) -> Dict[str, Any]:
        """
        Retrieves current weather conditions from Open-Meteo for Clothing Context integration,
        reusing the existing Open-Meteo endpoint while preserving normalized agent metrics.
        """
        lat, lon = validate_coordinates(latitude, longitude)

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation",
                "wind_speed_10m",
                "weather_code",
            ],
            "timezone": timezone,
        }

        data = self._perform_request(self.base_url, params)
        return self.parse_current_response(data)

    def validate_forecast_window(
        self,
        target_date: datetime.date,
        period: Optional[str] = None,
        reference_date: Optional[datetime.date] = None,
    ) -> None:
        ref = reference_date or datetime.date.today()
        delta_days = (target_date - ref).days
        if delta_days < 0:
            raise UnsupportedForecastError(
                f"Requested date {target_date.isoformat()} is in the past relative to {ref.isoformat()}."
            )
        if delta_days > self.max_forecast_days:
            raise UnsupportedForecastError(
                f"Requested date {target_date.isoformat()} is {delta_days} days ahead, "
                f"exceeding the {self.max_forecast_days}-day Open-Meteo forecast range."
            )
        if period is not None and period not in PERIOD_HOUR_RANGES:
            raise UnsupportedForecastError(f"Unsupported forecast period '{period}'.")

    def parse_forecast_response(
        self,
        raw_payload: Any,
        target_date: datetime.date,
        period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates and normalizes a raw Open-Meteo hourly/daily forecast JSON payload."""
        data = self._validate_provider_envelope(raw_payload)
        date_str = target_date.isoformat()
        resolved_tz = data.get("timezone") if isinstance(data.get("timezone"), str) else None

        hourly = data.get("hourly") if isinstance(data.get("hourly"), dict) else None
        daily = data.get("daily") if isinstance(data.get("daily"), dict) else None

        hourly_units = data.get("hourly_units") if isinstance(data.get("hourly_units"), dict) else {}
        daily_units = data.get("daily_units") if isinstance(data.get("daily_units"), dict) else {}
        temp_unit = _normalize_temp_unit(
            hourly_units.get("temperature_2m") or daily_units.get("temperature_2m_max")
        )
        wind_unit = str(
            hourly_units.get("wind_speed_10m") or daily_units.get("wind_speed_10m_max") or "km/h"
        )
        precip_unit = str(
            hourly_units.get("precipitation") or daily_units.get("precipitation_sum") or "mm"
        )

        if period is not None:
            if not hourly or not isinstance(hourly.get("time"), list) or not hourly["time"]:
                raise WeatherMissingFieldsError(
                    f"Provider response missing hourly forecast series required for period '{period}'."
                )
            return self._extract_hourly_window(
                hourly=hourly,
                date_str=date_str,
                period=period,
                resolved_tz=resolved_tz,
                temp_unit=temp_unit,
                wind_unit=wind_unit,
                precip_unit=precip_unit,
            )

        if daily and isinstance(daily.get("time"), list) and daily["time"]:
            return self._extract_daily_summary(
                daily=daily,
                hourly=hourly,
                date_str=date_str,
                resolved_tz=resolved_tz,
                temp_unit=temp_unit,
                wind_unit=wind_unit,
                precip_unit=precip_unit,
            )

        if hourly and isinstance(hourly.get("time"), list) and hourly["time"]:
            return self._extract_hourly_window(
                hourly=hourly,
                date_str=date_str,
                period=None,
                resolved_tz=resolved_tz,
                temp_unit=temp_unit,
                wind_unit=wind_unit,
                precip_unit=precip_unit,
            )

        raise WeatherMissingFieldsError("Provider forecast response missing both 'daily' and 'hourly' data.")

    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        target_date: datetime.date,
        period: Optional[str] = None,
        reference_date: Optional[datetime.date] = None,
        timezone: str = "auto",
    ) -> Dict[str, Any]:
        """
        Retrieves date-specific or time-window-specific forecast weather from Open-Meteo.
        Never substitutes current observations when forecast data is unavailable or out of range.
        """
        lat, lon = validate_coordinates(latitude, longitude)
        self.validate_forecast_window(
            target_date=target_date,
            period=period,
            reference_date=reference_date,
        )

        date_str = target_date.isoformat()
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "weather_code",
            ],
            "daily": [
                "temperature_2m_max",
                "temperature_2m_min",
                "apparent_temperature_max",
                "apparent_temperature_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "weather_code",
            ],
            "timezone": timezone,
        }

        data = self._perform_request(self.base_url, params)
        return self.parse_forecast_response(data, target_date=target_date, period=period)

    def _extract_hourly_window(
        self,
        hourly: Dict[str, Any],
        date_str: str,
        period: Optional[str],
        resolved_tz: Optional[str],
        temp_unit: str,
        wind_unit: str,
        precip_unit: str,
    ) -> Dict[str, Any]:
        times = hourly.get("time", [])
        if period is not None:
            start_h, end_h = PERIOD_HOUR_RANGES[period]
        else:
            start_h, end_h = (0, 23)

        indices: List[int] = []
        for idx, raw_ts in enumerate(times):
            if not isinstance(raw_ts, str):
                continue
            try:
                parsed_dt = datetime.datetime.fromisoformat(raw_ts)
            except ValueError:
                continue
            if parsed_dt.date().isoformat() == date_str and start_h <= parsed_dt.hour <= end_h:
                indices.append(idx)

        if not indices:
            raise WeatherMissingFieldsError(
                f"No hourly forecast entries matched {date_str}"
                + (f" ({period})" if period else "")
            )

        def collect_required(key: str) -> List[float]:
            arr = hourly.get(key)
            if not isinstance(arr, list):
                raise WeatherMissingFieldsError(f"Hourly forecast missing required array '{key}'.")
            vals: List[float] = []
            for i in indices:
                if i >= len(arr) or arr[i] is None:
                    raise WeatherMissingFieldsError(f"Hourly forecast field '{key}' missing value at index {i}.")
                vals.append(_to_finite_float(arr[i], key))
            return vals

        def collect_optional(key: str) -> List[float]:
            arr = hourly.get(key)
            if not isinstance(arr, list):
                return []
            vals: List[float] = []
            for i in indices:
                if i < len(arr) and arr[i] is not None:
                    vals.append(_to_finite_float(arr[i], key))
            return vals

        temps = collect_required("temperature_2m")
        precip_vals = collect_required("precipitation")
        winds = collect_required("wind_speed_10m")
        humidities = collect_optional("relative_humidity_2m")
        feels_vals = collect_optional("apparent_temperature")
        precip_probs = collect_optional("precipitation_probability")

        mean_temp = round(sum(temps) / len(temps), 1)
        min_temp = round(min(temps), 1)
        max_temp = round(max(temps), 1)
        feels_like = round(sum(feels_vals) / len(feels_vals), 1) if feels_vals else None
        humidity_ratio = round((sum(humidities) / len(humidities)) / 100.0, 4) if humidities else None
        precip_total_mm = round(sum(precip_vals), 3)
        precip_prob = round(max(precip_probs), 1) if precip_probs else None
        mean_wind = round(sum(winds) / len(winds), 1)

        condition: Optional[str] = None
        codes_arr = hourly.get("weather_code")
        if isinstance(codes_arr, list):
            mid_idx = indices[len(indices) // 2]
            if mid_idx < len(codes_arr):
                condition = _decode_wmo_condition(codes_arr[mid_idx])

        forecast_label = f"{date_str} {period}" if period else date_str

        return {
            "temp": mean_temp,
            "temp_min": min_temp,
            "temp_max": max_temp,
            "feels_like": feels_like,
            "humidity_ratio": humidity_ratio,
            "precipitation_mm": precip_total_mm,
            "precipitation_probability": precip_prob,
            "wind_speed": mean_wind,
            "condition": condition,
            "observed_at": None,
            "forecast_for": forecast_label,
            "timezone": resolved_tz,
            "units": {
                "temperature": temp_unit,
                "wind_speed": wind_unit,
                "precipitation": precip_unit,
            },
            "agent_metrics": (
                {
                    "temp": mean_temp,
                    "humidity": humidity_ratio,
                    "precipitation": min(precip_total_mm, 100.0) / 100.0,
                    "wind_speed": mean_wind,
                }
                if humidity_ratio is not None
                else None
            ),
        }

    def _extract_daily_summary(
        self,
        daily: Dict[str, Any],
        hourly: Optional[Dict[str, Any]],
        date_str: str,
        resolved_tz: Optional[str],
        temp_unit: str,
        wind_unit: str,
        precip_unit: str,
    ) -> Dict[str, Any]:
        times = daily.get("time", [])
        day_idx = 0
        for idx, t in enumerate(times):
            if str(t).startswith(date_str):
                day_idx = idx
                break

        def get_daily_req(key: str) -> float:
            arr = daily.get(key)
            if not isinstance(arr, list) or day_idx >= len(arr) or arr[day_idx] is None:
                raise WeatherMissingFieldsError(f"Daily forecast missing required field '{key}'.")
            return _to_finite_float(arr[day_idx], key)

        def get_daily_opt(key: str) -> Optional[float]:
            arr = daily.get(key)
            if not isinstance(arr, list) or day_idx >= len(arr) or arr[day_idx] is None:
                return None
            return _to_finite_float(arr[day_idx], key)

        t_max = get_daily_req("temperature_2m_max")
        t_min = get_daily_req("temperature_2m_min")
        precip_sum = get_daily_req("precipitation_sum")
        wind_max = get_daily_req("wind_speed_10m_max")

        temp_mid = round((t_max + t_min) / 2.0, 1)

        feel_max = get_daily_opt("apparent_temperature_max")
        feel_min = get_daily_opt("apparent_temperature_min")
        feels_like = (
            round((feel_max + feel_min) / 2.0, 1)
            if (feel_max is not None and feel_min is not None)
            else (feel_max if feel_max is not None else feel_min)
        )

        precip_prob = get_daily_opt("precipitation_probability_max")

        humidity_ratio: Optional[float] = None
        if hourly and isinstance(hourly.get("relative_humidity_2m"), list):
            h_vals = [
                _to_finite_float(v, "relative_humidity_2m")
                for v in hourly["relative_humidity_2m"]
                if v is not None
            ]
            if h_vals:
                humidity_ratio = round((sum(h_vals) / len(h_vals)) / 100.0, 4)

        condition: Optional[str] = None
        codes_arr = daily.get("weather_code")
        if isinstance(codes_arr, list) and day_idx < len(codes_arr):
            condition = _decode_wmo_condition(codes_arr[day_idx])

        return {
            "temp": temp_mid,
            "temp_min": round(t_min, 1),
            "temp_max": round(t_max, 1),
            "feels_like": feels_like,
            "humidity_ratio": humidity_ratio,
            "precipitation_mm": round(precip_sum, 3),
            "precipitation_probability": round(precip_prob, 1) if precip_prob is not None else None,
            "wind_speed": round(wind_max, 1),
            "condition": condition,
            "observed_at": None,
            "forecast_for": date_str,
            "timezone": resolved_tz,
            "units": {
                "temperature": temp_unit,
                "wind_speed": wind_unit,
                "precipitation": precip_unit,
            },
            "agent_metrics": (
                {
                    "temp": temp_mid,
                    "humidity": humidity_ratio,
                    "precipitation": min(precip_sum, 100.0) / 100.0,
                    "wind_speed": round(wind_max, 1),
                }
                if humidity_ratio is not None
                else None
            ),
        }

    def parse_geocoding_response(
        self,
        raw_payload: Any,
        fallback_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Validates and extracts top match from an Open-Meteo Geocoding JSON payload."""
        data = self._validate_provider_envelope(raw_payload)
        results = data.get("results")
        if not isinstance(results, list) or len(results) == 0:
            return None

        top = results[0]
        if not isinstance(top, dict):
            raise WeatherResponseError("Geocoding provider returned malformed result item.")

        if top.get("latitude") is None or top.get("longitude") is None:
            raise WeatherMissingFieldsError("Geocoding provider result missing coordinates.")

        lat, lon = validate_coordinates(top["latitude"], top["longitude"])
        return {
            "name": str(top.get("name") or fallback_name),
            "latitude": lat,
            "longitude": lon,
            "country": str(top["country"]) if top.get("country") else None,
            "timezone": str(top["timezone"]) if top.get("timezone") else None,
        }

    def geocode_location(self, location_query: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a city/place name to geographic coordinates via Open-Meteo Geocoding API.
        Returns None if the provider reports no matching places.
        """
        cleaned = (location_query or "").strip()
        if not cleaned:
            return None

        data = self._perform_request(
            self.geocoding_url,
            {
                "name": cleaned,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        return self.parse_geocoding_response(data, fallback_name=cleaned)


if __name__ == "__main__":

    agent = WeatherAgent()

    weather = agent.get_weather(
        latitude=35.6892,
        longitude=51.3890
    )

    print(weather)
