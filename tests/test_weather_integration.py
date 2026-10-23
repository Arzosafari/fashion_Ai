"""
Comprehensive Automated Test Suite for Fashion AI Weather Context Integration.

Covers all 15 required test dimensions (Section 12):
  1. Successful current weather retrieval (preserving WeatherAgent.get_weather + structured WeatherContext)
  2. Explicit location resolution & priority rules (request > settings > unavailable; geocoding fallback)
  3. Missing location handling (including non-geographic venue words such as 'outdoor' / 'office')
  4. Invalid location & coordinate validation
  5. Forecast retrieval (whole-day daily forecasts and sub-day hourly windows: morning / afternoon / evening)
  6. Unsupported forecast dates (past dates, beyond 16-day horizon, unparseable dates, current-only stubs)
  7. Missing weather fields vs optional weather fields (zero fabricated values)
  8. Weather API timeout resilience
  9. Network failure resilience
  10. Malformed provider responses, rate limiting (HTTP 429), and invalid credentials (HTTP 401/403)
  11. TTL caching & stale cache invalidation (never presenting expired observations as live weather)
  12. Strict separation between WeatherContext and FashionRequestOutput / user preferences
  13. End-to-end compatibility with the existing Voice Input + Transcript Editing pipeline
  14. End-to-end compatibility with the existing Typed Input pipeline (parity between voice and text)
  15. Opt-in / environment-gated live Open-Meteo provider integration test (clearly separated from mocked tests)
"""

import datetime
import os
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import requests
from fastapi.testclient import TestClient

from agents.weather_agent import WeatherAgent
from fashion_stt.extractor import FashionEntityExtractor
from fashion_stt.server import create_app
from fashion_stt.weather_context import (
    ContextIntegrator,
    LocationResolver,
    WeatherCache,
    WeatherConfig,
    WeatherContextService,
    get_weather_context,
)

FIXED_REF_DATE = datetime.date(2026, 10, 23)  # Friday


def _mock_http_response(
    status_code: int = 200,
    json_payload: Any = None,
    raw_json_error: bool = False,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if raw_json_error:
        resp.json.side_effect = ValueError("No JSON object could be decoded")
    else:
        resp.json.return_value = json_payload
    if status_code >= 400:
        err = requests.exceptions.HTTPError(f"HTTP {status_code}", response=resp)
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


def _sample_current_payload(
    temp: float = 12.4,
    feels_like: Any = 9.8,
    humidity: float = 72.0,
    precip: float = 1.6,
    wind: float = 18.5,
    weather_code: Any = 61,
    obs_time: str = "2026-10-23T13:15",
    timezone: str = "America/New_York",
) -> Dict[str, Any]:
    current: Dict[str, Any] = {
        "time": obs_time,
        "temperature_2m": temp,
        "relative_humidity_2m": humidity,
        "precipitation": precip,
        "wind_speed_10m": wind,
    }
    if feels_like is not None:
        current["apparent_temperature"] = feels_like
    if weather_code is not None:
        current["weather_code"] = weather_code
    return {
        "timezone": timezone,
        "current_units": {
            "temperature_2m": "°C",
            "apparent_temperature": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "wind_speed_10m": "km/h",
        },
        "current": current,
    }


def _sample_forecast_payload(target_date: str = "2026-10-24") -> Dict[str, Any]:
    hours = [f"{target_date}T{h:02d}:00" for h in range(24)]
    return {
        "timezone": "America/New_York",
        "hourly_units": {
            "temperature_2m": "°C",
            "apparent_temperature": "°C",
            "precipitation": "mm",
            "wind_speed_10m": "km/h",
        },
        "hourly": {
            "time": hours,
            # Cool morning (~9C), milder afternoon (~16C), crisp evening (~11C)
            "temperature_2m": [
                7.0, 7.0, 6.5, 6.5, 6.5, 7.0, 7.5, 8.0,
                8.5, 9.0, 9.5, 11.0,  # 08:00-11:00 mean = 9.5
                13.0, 15.0, 16.5, 17.0, 16.0, 14.5,  # 12:00-17:00
                12.5, 11.5, 10.5, 9.5,  # 18:00-21:00
                9.0, 8.5,
            ],
            "apparent_temperature": [
                5.0, 5.0, 4.5, 4.5, 4.5, 5.0, 5.5, 6.0,
                6.5, 7.0, 7.5, 9.0,
                11.5, 13.5, 15.0, 15.5, 14.5, 13.0,
                10.5, 9.5, 8.5, 7.5,
                7.0, 6.5,
            ],
            "relative_humidity_2m": [80.0] * 24,
            "precipitation_probability": [
                10, 10, 10, 15, 20, 25, 30, 35,
                40, 55, 65, 50,  # morning max = 65%
                20, 15, 10, 10, 15, 20,  # afternoon max = 20%
                25, 30, 30, 25,
                20, 15,
            ],
            "precipitation": [
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                0.4, 0.8, 1.0, 0.3,  # morning total = 2.5 mm
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0,
                0.0, 0.0,
            ],
            "wind_speed_10m": [14.0] * 24,
            "weather_code": [
                2, 2, 2, 2, 2, 2, 2, 2,
                61, 61, 61, 3,
                1, 1, 0, 0, 1, 2,
                2, 2, 3, 3,
                2, 2,
            ],
        },
        "daily_units": {
            "temperature_2m_max": "°C",
            "temperature_2m_min": "°C",
            "precipitation_sum": "mm",
            "wind_speed_10m_max": "km/h",
        },
        "daily": {
            "time": [target_date],
            "temperature_2m_max": [17.0],
            "temperature_2m_min": [6.5],
            "apparent_temperature_max": [15.5],
            "apparent_temperature_min": [4.5],
            "precipitation_sum": [2.5],
            "precipitation_probability_max": [65.0],
            "wind_speed_10m_max": [21.0],
            "weather_code": [61],
        },
    }


class TestMockedWeatherModuleIntegration(unittest.TestCase):
    """Unit and FastAPI pipeline tests using mocked HTTP responses."""

    def _make_service(
        self,
        ttl_seconds: int = 600,
        clock=None,
        config: WeatherConfig = None,
        weather_agent: Any = None,
    ) -> WeatherContextService:
        cfg = config or WeatherConfig(cache_ttl_seconds=ttl_seconds)
        cache = WeatherCache(
            ttl_seconds=ttl_seconds,
            clock=clock or (lambda: datetime.datetime(2026, 10, 23, 13, 20, tzinfo=datetime.timezone.utc)),
        )
        return WeatherContextService(
            weather_agent=weather_agent,
            config=cfg,
            cache=cache,
            reference_date=FIXED_REF_DATE,
        )

    # ------------------------------------------------------------------
    # 1. Successful Weather Retrieval + Existing WeatherAgent Preservation
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_01_existing_weather_agent_get_weather_preserved(self, mock_get):
        """Verifies existing WeatherAgent.get_weather(lat, lon) signature & normalized keys remain intact."""
        mock_get.return_value = _mock_http_response(
            200,
            _sample_current_payload(temp=21.5, humidity=45.0, precip=3.0, wind=12.2),
        )
        agent = WeatherAgent()
        result = agent.get_weather(latitude=35.6892, longitude=51.3890)

        self.assertEqual(set(result.keys()), {"temp", "humidity", "precipitation", "wind_speed"})
        self.assertAlmostEqual(result["temp"], 21.5)
        self.assertAlmostEqual(result["humidity"], 0.45)
        self.assertAlmostEqual(result["precipitation"], 0.03)
        self.assertAlmostEqual(result["wind_speed"], 12.2)

    @patch("agents.weather_agent.requests.get")
    def test_02_successful_weather_context_retrieval(self, mock_get):
        """Verifies structured WeatherContext retrieval for current observations."""
        mock_get.return_value = _mock_http_response(200, _sample_current_payload())
        service = self._make_service()

        ctx = get_weather_context(location="Boston", service=service)
        self.assertTrue(ctx.available)
        self.assertEqual(ctx.status, "ok")
        self.assertEqual(ctx.mode, "current")
        self.assertEqual(ctx.location.name, "Boston")
        self.assertEqual(ctx.location.source, "request")
        self.assertEqual(ctx.observed_at, "2026-10-23T13:15")
        self.assertIsNone(ctx.forecast_for)
        self.assertEqual(ctx.temperature.value, 12.4)
        self.assertEqual(ctx.temperature.unit, "C")
        self.assertEqual(ctx.feels_like.value, 9.8)
        self.assertEqual(ctx.condition, "light_rain")
        self.assertAlmostEqual(ctx.humidity.value, 0.72)
        self.assertEqual(ctx.precipitation.value, 1.6)
        self.assertEqual(ctx.precipitation.unit, "mm")
        self.assertEqual(ctx.wind_speed.value, 18.5)
        self.assertEqual(ctx.wind_speed.unit, "km/h")
        self.assertEqual(ctx.source, "open-meteo")
        self.assertFalse(ctx.cached)
        self.assertIsNotNone(ctx.agent_metrics)

    # ------------------------------------------------------------------
    # 2. Explicit Location Priority & Geocoding
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_03_explicit_request_location_overrides_application_setting(self, mock_get):
        """Priority 1 (explicit city in user request) overrides Priority 2 (application fallback location)."""
        mock_get.return_value = _mock_http_response(200, _sample_current_payload())
        cfg = WeatherConfig(default_location="Dallas")
        service = self._make_service(config=cfg)
        extractor = FashionEntityExtractor(reference_date=FIXED_REF_DATE)
        integrator = ContextIntegrator(service)

        req = extractor.extract("I want a casual look for walking around New York.")
        combined = integrator.build_context(req, fallback_location="Tehran")

        self.assertTrue(combined.weather_context.available)
        self.assertEqual(combined.weather_context.location.name, "New York")
        self.assertEqual(combined.weather_context.location.source, "request")

    @patch("agents.weather_agent.requests.get")
    def test_04_geocoding_for_non_gazetteer_city(self, mock_get):
        """Verifies arbitrary cities outside the built-in gazetteer resolve cleanly via Open-Meteo Geocoding."""
        mock_get.side_effect = [
            _mock_http_response(
                200,
                {
                    "results": [
                        {
                            "name": "Ithaca",
                            "latitude": 42.4440,
                            "longitude": -76.5019,
                            "country": "United States",
                            "timezone": "America/New_York",
                        }
                    ]
                },
            ),
            _mock_http_response(200, _sample_current_payload(temp=8.2)),
        ]
        service = self._make_service()
        ctx = service.get_weather_context(location="Ithaca")

        self.assertTrue(ctx.available)
        self.assertEqual(ctx.location.name, "Ithaca")
        self.assertAlmostEqual(ctx.location.latitude, 42.4440)
        self.assertEqual(ctx.temperature.value, 8.2)

    # ------------------------------------------------------------------
    # 3. Missing Location (Never Fabricates a Fallback City)
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_05_missing_location_returns_explicit_unavailable_state(self, mock_get):
        """Missing location never invents a city and never calls external network."""
        service = self._make_service()
        extractor = FashionEntityExtractor(reference_date=FIXED_REF_DATE)
        integrator = ContextIntegrator(service)

        # Case A: No location in utterance or settings
        req_none = extractor.extract("Can you help me put together an outfit for a wedding?")
        res_none = integrator.build_context(req_none)
        self.assertFalse(res_none.weather_context.available)
        self.assertEqual(res_none.weather_context.status, "missing_location")
        self.assertIsNone(res_none.weather_context.location)
        self.assertIsNone(res_none.weather_context.temperature)

        # Case B: Non-geographic venue word ("outdoor") without city
        req_venue = extractor.extract("I need a warm outfit for an outdoor event.")
        self.assertEqual(req_venue.location.value, "outdoor")
        res_venue = integrator.build_context(req_venue)
        self.assertFalse(res_venue.weather_context.available)
        self.assertEqual(res_venue.weather_context.status, "missing_location")
        mock_get.assert_not_called()

    # ------------------------------------------------------------------
    # 4. Invalid Location & Coordinate Validation
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_06_invalid_locations_and_coordinates_handled_safely(self, mock_get):
        mock_get.return_value = _mock_http_response(200, {"results": []})
        service = self._make_service()

        # Unknown place name rejected by geocoder
        unknown_ctx = service.get_weather_context(location="NonExistentAtlantisXYZ")
        self.assertFalse(unknown_ctx.available)
        self.assertEqual(unknown_ctx.status, "invalid_location")

        # Out-of-bounds latitude (> 90)
        bad_lat_ctx = service.get_weather_context(latitude=95.0, longitude=10.0)
        self.assertFalse(bad_lat_ctx.available)
        self.assertEqual(bad_lat_ctx.status, "invalid_location")

        # Out-of-bounds longitude (< -180)
        bad_lon_ctx = service.get_weather_context(latitude=35.0, longitude=-195.0)
        self.assertFalse(bad_lon_ctx.available)
        self.assertEqual(bad_lon_ctx.status, "invalid_location")

        # Partial coordinate missing longitude
        half_coord_ctx = service.get_weather_context(latitude=42.36)
        self.assertFalse(half_coord_ctx.available)
        self.assertEqual(half_coord_ctx.status, "invalid_location")

        # Non-place punctuation string
        punct_ctx = service.get_weather_context(location="???")
        self.assertFalse(punct_ctx.available)
        self.assertEqual(punct_ctx.status, "invalid_location")

    # ------------------------------------------------------------------
    # 5. Forecast Retrieval (Daily & Time-of-Day Windows)
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_07_forecast_retrieval_daily_and_time_of_day_windows(self, mock_get):
        """Verifies Section 7 temporal cases: tomorrow morning, this afternoon, this Saturday."""
        service = self._make_service()
        extractor = FashionEntityExtractor(reference_date=FIXED_REF_DATE)  # Friday 2026-10-23
        integrator = ContextIntegrator(service)

        # Case A: "tomorrow morning" -> 2026-10-24 morning hourly window
        mock_get.return_value = _mock_http_response(200, _sample_forecast_payload("2026-10-24"))
        req_morning = extractor.extract("I need an outfit for tomorrow morning in Boston.")
        ctx_morning = integrator.build_context(req_morning).weather_context
        self.assertTrue(ctx_morning.available)
        self.assertEqual(ctx_morning.mode, "forecast")
        self.assertEqual(ctx_morning.forecast_for, "2026-10-24 morning")
        self.assertIsNone(ctx_morning.observed_at)
        self.assertAlmostEqual(ctx_morning.temperature.value, 9.5)
        self.assertAlmostEqual(ctx_morning.precipitation_probability, 65.0)

        # Case B: "this afternoon" -> 2026-10-23 afternoon hourly window
        mock_get.return_value = _mock_http_response(200, _sample_forecast_payload("2026-10-23"))
        req_afternoon = extractor.extract("I need an outfit for this afternoon in Boston.")
        ctx_afternoon = integrator.build_context(req_afternoon).weather_context
        self.assertTrue(ctx_afternoon.available)
        self.assertEqual(ctx_afternoon.mode, "forecast")
        self.assertEqual(ctx_afternoon.forecast_for, "2026-10-23 afternoon")
        self.assertAlmostEqual(ctx_afternoon.precipitation_probability, 20.0)

        # Case C: "an outdoor event this Saturday" -> whole-day daily forecast for 2026-10-24
        mock_get.return_value = _mock_http_response(200, _sample_forecast_payload("2026-10-24"))
        req_sat = extractor.extract("I need an outfit for an outdoor event this Saturday in Boston.")
        self.assertEqual(req_sat.location.value, "Boston")
        ctx_sat = integrator.build_context(req_sat).weather_context
        self.assertTrue(ctx_sat.available)
        self.assertEqual(ctx_sat.mode, "forecast")
        self.assertEqual(ctx_sat.forecast_for, "2026-10-24")
        self.assertEqual(ctx_sat.temperature_range.min, 6.5)
        self.assertEqual(ctx_sat.temperature_range.max, 17.0)

    # ------------------------------------------------------------------
    # 6. Unsupported Forecast Dates (Never Substitutes Current Weather)
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_08_unsupported_forecast_dates_never_substitute_current_weather(self, mock_get):
        service = self._make_service()

        # Beyond 16-day forecast horizon
        far_future = service.get_weather_context(location="Paris", date_or_time="2026-12-20")
        self.assertFalse(far_future.available)
        self.assertEqual(far_future.status, "unsupported_forecast_date")
        self.assertEqual(far_future.mode, "forecast")
        self.assertIsNone(far_future.temperature)

        # Past historical date
        past_date = service.get_weather_context(location="Paris", date_or_time="2025-05-01")
        self.assertFalse(past_date.available)
        self.assertEqual(past_date.status, "unsupported_forecast_date")

        # Unparseable date expression
        bad_expr = service.get_weather_context(location="Paris", date_or_time="invalid-date-token")
        self.assertFalse(bad_expr.available)
        self.assertEqual(bad_expr.status, "unsupported_forecast_date")

        mock_get.assert_not_called()

    # ------------------------------------------------------------------
    # 7. Missing Weather Fields vs Optional Fields
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_09_missing_required_and_optional_weather_fields(self, mock_get):
        service = self._make_service(ttl_seconds=0)

        # Missing required wind_speed_10m -> missing_weather_fields, zero fabricated defaults
        mock_get.return_value = _mock_http_response(
            200,
            {"current": {"temperature_2m": 15.0, "relative_humidity_2m": 50.0, "precipitation": 0.0}},
        )
        missing_ctx = service.get_weather_context(location="London")
        self.assertFalse(missing_ctx.available)
        self.assertEqual(missing_ctx.status, "missing_weather_fields")
        self.assertIsNone(missing_ctx.temperature)

        # Missing optional apparent_temperature & weather_code -> succeeds with None for optional fields
        mock_get.return_value = _mock_http_response(
            200,
            _sample_current_payload(temp=16.0, feels_like=None, weather_code=None),
        )
        minimal_ctx = service.get_weather_context(location="London")
        self.assertTrue(minimal_ctx.available)
        self.assertEqual(minimal_ctx.temperature.value, 16.0)
        self.assertIsNone(minimal_ctx.feels_like)
        self.assertIsNone(minimal_ctx.condition)
        self.assertIsNone(minimal_ctx.precipitation_probability)

    # ------------------------------------------------------------------
    # 8, 9, 10. Timeout, Network Failure, Malformed Response, 429 & 401
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_10_timeout_network_malformed_rate_limit_and_auth_errors(self, mock_get):
        service = self._make_service(ttl_seconds=0)

        # Timeout
        mock_get.side_effect = requests.exceptions.ReadTimeout("Read timed out")
        c_timeout = service.get_weather_context(location="Berlin")
        self.assertFalse(c_timeout.available)
        self.assertEqual(c_timeout.status, "timeout")

        # Network connection failure
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
        c_net = service.get_weather_context(location="Berlin")
        self.assertFalse(c_net.available)
        self.assertEqual(c_net.status, "network_error")

        # Malformed non-JSON body
        mock_get.side_effect = None
        mock_get.return_value = _mock_http_response(200, raw_json_error=True)
        c_bad_json = service.get_weather_context(location="Berlin")
        self.assertFalse(c_bad_json.available)
        self.assertEqual(c_bad_json.status, "invalid_response")

        # Rate limit (HTTP 429)
        mock_get.return_value = _mock_http_response(429, {"error": True, "reason": "Rate limit exceeded"})
        c_rate = service.get_weather_context(location="Berlin")
        self.assertFalse(c_rate.available)
        self.assertEqual(c_rate.status, "rate_limited")

        # Invalid API credentials (HTTP 401)
        mock_get.return_value = _mock_http_response(401, {"error": True, "reason": "Invalid API key"})
        c_auth = service.get_weather_context(location="Berlin")
        self.assertFalse(c_auth.available)
        self.assertEqual(c_auth.status, "invalid_credentials")

    # ------------------------------------------------------------------
    # 11. Caching & Stale Data Prevention
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_11_ttl_cache_hits_and_stale_data_invalidation(self, mock_get):
        now_box: List[datetime.datetime] = [
            datetime.datetime(2026, 10, 23, 12, 0, 0, tzinfo=datetime.timezone.utc)
        ]
        service = self._make_service(ttl_seconds=300, clock=lambda: now_box[0])

        # Initial live fetch at T=0
        mock_get.return_value = _mock_http_response(200, _sample_current_payload(temp=14.0))
        first = service.get_weather_context(location="Tehran")
        self.assertTrue(first.available)
        self.assertFalse(first.cached)
        self.assertEqual(first.fetched_at, "2026-10-23T12:00:00Z")
        self.assertEqual(first.cache_expires_at, "2026-10-23T12:05:00Z")
        self.assertEqual(mock_get.call_count, 1)

        # Within TTL (T + 120s): served from cache without network call, explicitly marked cached=True
        now_box[0] = datetime.datetime(2026, 10, 23, 12, 2, 0, tzinfo=datetime.timezone.utc)
        second = service.get_weather_context(location="Tehran")
        self.assertTrue(second.available)
        self.assertTrue(second.cached)
        self.assertEqual(mock_get.call_count, 1)

        # Past TTL (T + 301s) and network fails: stale cached entry MUST NOT be returned as live weather
        now_box[0] = datetime.datetime(2026, 10, 23, 12, 5, 1, tzinfo=datetime.timezone.utc)
        mock_get.side_effect = requests.exceptions.ConnectionError("Provider unreachable")
        stale_attempt = service.get_weather_context(location="Tehran")
        self.assertFalse(stale_attempt.available)
        self.assertEqual(stale_attempt.status, "network_error")
        self.assertIsNone(stale_attempt.temperature)
        self.assertEqual(mock_get.call_count, 2)

    # ------------------------------------------------------------------
    # 12. Strict Separation Between Weather Context & User Request
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_12_strict_separation_of_weather_and_user_preferences(self, mock_get):
        mock_get.return_value = _mock_http_response(
            200,
            _sample_current_payload(temp=2.0, precip=14.0, wind=35.0, weather_code=65),
        )
        service = self._make_service()
        extractor = FashionEntityExtractor(reference_date=FIXED_REF_DATE)
        integrator = ContextIntegrator(service)

        utterance = "Give me something minimalist in navy for a business meeting in Boston."
        extracted = extractor.extract(utterance)
        snapshot_before = extracted.model_dump()

        combined = integrator.build_context(extracted)

        # Original request object AND integrated request_context are completely untouched by cold/heavy-rain weather
        self.assertEqual(extracted.model_dump(), snapshot_before)
        self.assertEqual(combined.request_context.model_dump(), snapshot_before)
        self.assertEqual(combined.request_context.raw_input, utterance)
        self.assertEqual([s.value for s in combined.request_context.style_preferences], ["minimalist"])
        self.assertEqual(combined.request_context.functional_requirements, [])
        self.assertEqual(combined.weather_context.condition, "heavy_rain")

    # ------------------------------------------------------------------
    # 13 & 14. FastAPI Endpoints + Voice Input Flow + Typed Input Flow + Resilience
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_13_voice_and_typed_pipeline_and_weather_endpoint_integration(self, mock_get):
        mock_get.return_value = _mock_http_response(200, _sample_forecast_payload("2026-10-24"))
        service = self._make_service()
        test_app = create_app(weather_service=service, reference_date=FIXED_REF_DATE)
        client = TestClient(test_app)

        # Standalone GET /api/weather endpoint
        w_res = client.get("/api/weather", params={"location": "Boston", "date_or_time": "tomorrow morning"})
        self.assertEqual(w_res.status_code, 200)
        w_json = w_res.json()
        self.assertTrue(w_json["available"])
        self.assertEqual(w_json["mode"], "forecast")
        self.assertEqual(w_json["forecast_for"], "2026-10-24 morning")

        # Voice input flow: real audio transcription -> user review edit -> POST /api/understand
        sample_wav = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "public",
            "samples",
            "sample_dress.wav",
        )
        with open(sample_wav, "rb") as audio_file:
            transcribe_res = client.post(
                "/api/transcribe",
                files={"file": ("sample_dress.wav", audio_file, "audio/wav")},
            )
        self.assertEqual(transcribe_res.status_code, 200)
        raw_voice = transcribe_res.json()["raw_text"]
        edited_transcript = "Show me an emerald green silk slip dress for a wedding tomorrow in Boston"

        voice_res = client.post(
            "/api/understand",
            json={
                "text": edited_transcript,
                "input_method": "voice",
                "raw_transcript": raw_voice,
            },
        )
        typed_res = client.post(
            "/api/understand",
            json={
                "text": edited_transcript,
                "input_method": "text",
            },
        )
        self.assertEqual(voice_res.status_code, 200)
        self.assertEqual(typed_res.status_code, 200)

        v_body = voice_res.json()
        t_body = typed_res.json()

        # Consistent extracted features & identical weather context regardless of voice vs typed input
        self.assertEqual(v_body["structured_data"]["occasion"], t_body["structured_data"]["occasion"])
        self.assertEqual(v_body["structured_data"]["colors"], t_body["structured_data"]["colors"])
        self.assertEqual(v_body["weather_context"]["available"], True)
        self.assertEqual(v_body["weather_context"]["forecast_for"], "2026-10-24")
        self.assertEqual(
            v_body["weather_context"]["temperature"],
            t_body["weather_context"]["temperature"],
        )

        # Provider timeout MUST NOT break /api/understand interaction pipeline
        mock_get.side_effect = requests.exceptions.Timeout("Upstream timeout")
        resilient_res = client.post(
            "/api/understand",
            json={"text": "Suggest an outfit for dinner tonight in Chicago.", "input_method": "text"},
        )
        self.assertEqual(resilient_res.status_code, 200)
        r_body = resilient_res.json()
        self.assertEqual(r_body["status"], "success")
        self.assertEqual(r_body["structured_data"]["occasion"]["value"], "dinner")
        self.assertFalse(r_body["weather_context"]["available"])
        self.assertEqual(r_body["weather_context"]["status"], "timeout")

    # ------------------------------------------------------------------
    # 15. Minimal Legacy get_weather()-Only Duck-Typed Agent Compatibility
    # ------------------------------------------------------------------
    def test_14_minimal_legacy_get_weather_only_stub_compatibility(self):
        class MinimalLegacyWeatherAgent:
            def get_weather(self, latitude: float, longitude: float) -> dict:
                return {
                    "temp": 19.5,
                    "humidity": 0.55,
                    "precipitation": 0.0,
                    "wind_speed": 10.2,
                }

        service = self._make_service(weather_agent=MinimalLegacyWeatherAgent())

        # Current weather works cleanly without fabricating missing fields
        cur = service.get_weather_context(latitude=35.6892, longitude=51.3890)
        self.assertTrue(cur.available)
        self.assertEqual(cur.temperature.value, 19.5)
        self.assertAlmostEqual(cur.humidity.value, 0.55)
        self.assertEqual(cur.wind_speed.value, 10.2)
        self.assertIsNone(cur.feels_like)
        self.assertIsNone(cur.condition)
        self.assertIsNone(cur.precipitation_probability)

        # Forecast request on current-only stub never substitutes current weather
        fut = service.get_weather_context(latitude=35.6892, longitude=51.3890, date_or_time="tomorrow")
        self.assertFalse(fut.available)
        self.assertEqual(fut.status, "unsupported_forecast_date")

    # ------------------------------------------------------------------
    # 16. Modular Pluggable Location Source & Multi-Turn Cache Reuse
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_15_pluggable_location_hook_and_multiturn_cache_reuse(self, mock_get):
        mock_get.return_value = _mock_http_response(200, _sample_forecast_payload("2026-10-24"))
        cfg = WeatherConfig(cache_ttl_seconds=600)
        resolver = LocationResolver(config=cfg, fallback_provider=lambda: "Boston")
        service = WeatherContextService(
            config=cfg,
            location_resolver=resolver,
            reference_date=FIXED_REF_DATE,
        )
        test_app = create_app(weather_service=service, reference_date=FIXED_REF_DATE)
        client = TestClient(test_app)

        sid = "multiturn_weather_session"
        t1 = client.post(
            "/api/understand",
            json={"text": "I need an outfit for a graduation ceremony tomorrow.", "session_id": sid},
        ).json()
        self.assertTrue(t1["weather_context"]["available"])
        self.assertEqual(t1["weather_context"]["location"]["name"], "Boston")
        self.assertEqual(t1["weather_context"]["location"]["source"], "settings")
        self.assertFalse(t1["weather_context"]["cached"])
        self.assertEqual(mock_get.call_count, 1)

        # Follow-up turn reuses cached forecast without second HTTP call and keeps preferences separate
        t2 = client.post(
            "/api/understand",
            json={"text": "Make it more minimalist and avoid black.", "session_id": sid},
        ).json()
        self.assertTrue(t2["weather_context"]["available"])
        self.assertTrue(t2["weather_context"]["cached"])
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(t2["structured_data"]["occasion"]["value"], "graduation")
        self.assertIn("black", t2["structured_data"]["colors"]["excluded"])

        hist = client.get(f"/api/session/{sid}").json()
        self.assertEqual(hist["turn_count"], 2)
        self.assertIn("active_request", hist)
        self.assertIn("weather_context", hist)
        self.assertNotIn("temperature", hist["active_request"])

    # ------------------------------------------------------------------
    # 17. Sandboxed-Container Client HTTPS Relay -> Backend Validation & Cache Warmup
    # ------------------------------------------------------------------
    @patch("agents.weather_agent.requests.get")
    def test_16_sandboxed_container_relay_resolution_and_backend_cache_warmup(self, mock_get):
        """
        Simulates a firewall-restricted container where outbound server requests raise ConnectionError:
          1. Turn 1 POST /api/understand returns structured request + network_error weather state.
          2. Client relays raw Open-Meteo payload to POST /api/weather/resolve -> validated & cached.
          3. Turn 2 follow-up POST /api/understand hits backend WeatherCache directly with cached=True!
        """
        mock_get.side_effect = requests.exceptions.ConnectionError("Sandbox outbound firewall")
        service = self._make_service(ttl_seconds=600)
        test_app = create_app(weather_service=service, reference_date=FIXED_REF_DATE)
        client = TestClient(test_app)

        sid = "sandbox_relay_session"
        t1 = client.post(
            "/api/understand",
            json={"text": "I need an outfit for tomorrow morning in Ithaca.", "session_id": sid},
        ).json()
        self.assertEqual(t1["structured_data"]["location"]["value"], "Ithaca")
        self.assertEqual(t1["weather_context"]["status"], "network_error")

        # Client relays Open-Meteo geocoding + forecast payloads for canonical backend validation
        relayed = client.post(
            "/api/weather/resolve",
            json={
                "session_id": sid,
                "location": "Ithaca",
                "location_source": "request",
                "date_or_time": "2026-10-24 morning",
                "geocoding_payload": {
                    "results": [
                        {
                            "name": "Ithaca",
                            "latitude": 42.4440,
                            "longitude": -76.5019,
                            "country": "United States",
                            "timezone": "America/New_York",
                        }
                    ]
                },
                "provider_payload": _sample_forecast_payload("2026-10-24"),
            },
        ).json()
        self.assertTrue(relayed["weather_context"]["available"])
        self.assertEqual(relayed["weather_context"]["status"], "ok")
        self.assertEqual(relayed["weather_context"]["location"]["name"], "Ithaca")
        self.assertEqual(relayed["weather_context"]["forecast_for"], "2026-10-24 morning")
        self.assertIsNotNone(relayed["recommendation_context"])

        # Subsequent follow-up turn for 'Ithaca' is served straight from backend caches (even offline!)
        t2 = client.post(
            "/api/understand",
            json={
                "text": "Make it minimalist in navy.",
                "session_id": sid,
            },
        ).json()
        self.assertTrue(t2["weather_context"]["available"])
        self.assertTrue(t2["weather_context"]["cached"])
        self.assertEqual(t2["weather_context"]["location"]["name"], "Ithaca")
        self.assertIn("navy", t2["structured_data"]["colors"]["preferred"])


def _can_reach_open_meteo() -> bool:
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": 35.6892, "longitude": 51.3890, "current": "temperature_2m"},
            timeout=3,
        )
        return resp.status_code == 200
    except Exception:
        return False


@unittest.skipUnless(
    _can_reach_open_meteo(),
    "Live Open-Meteo network access is blocked in this sandbox environment; run with internet access to execute live provider checks.",
)
class TestLiveOpenMeteoProviderIntegration(unittest.TestCase):
    """Real network integration tests against https://api.open-meteo.com/v1/forecast."""

    def test_live_current_and_forecast_weather_retrieval(self):
        service = WeatherContextService()

        current_ctx = service.get_weather_context(location="Boston")
        self.assertTrue(current_ctx.available)
        self.assertEqual(current_ctx.mode, "current")
        self.assertIsNotNone(current_ctx.temperature)

        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        forecast_ctx = service.get_weather_context(location="Boston", date_or_time=tomorrow)
        self.assertTrue(forecast_ctx.available)
        self.assertEqual(forecast_ctx.mode, "forecast")
        self.assertEqual(forecast_ctx.forecast_for, tomorrow)


if __name__ == "__main__":
    unittest.main()
