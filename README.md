# Fashion AI — Request Understanding & Weather Context Integration

A modular, production-ready natural language understanding and contextual integration layer for **Fashion AI**. It accepts **English voice or typed input**, performs domain-optimized speech-to-text, maintains session-scoped multi-turn conversational memory, retrieves **independent environmental weather context** via **Open-Meteo** (`agents/weather_agent.py`), and produces **validated, machine-readable structured JSON** for the future Outfit Recommendation Engine.

---

## 🌟 Architecture & Request Lifecycle

```text
                       USER INPUT
                      /          \
               Voice Input    Typed Input
                      \          /
                Editable Text Request
                           |
           Request Processing & Phonetic Lexicon
                           |
             Structured User Request (Pydantic)
                           |
                           +------------------------+
                           |                        |
                           v                        v
            FashionRequestOutput           WeatherContextService
          (User Request Features)        (agents/weather_agent.py)
                           |                        |
                           |                 WeatherContext
                           |                        |
                           +-----------+------------+
                                       |
                              ContextIntegrator
                         (RecommendationContext JSON)
                                       |
                         Future Recommendation Engine
```

### Design Invariants
1. **Strict Separation of Concerns**: `FashionRequestOutput` captures *only* the user's request (`intent`, `occasion`, `location`, `time`, `style_preferences`, `garment_preferences`, `colors`, `fit_preferences`, `functional_requirements`, `constraints`). Environmental observations and forecasts live exclusively in `WeatherContext` and are never injected into user transcripts or converted into permanent style preferences.
2. **Existing Weather Module Preserved**: Reuses `agents/weather_agent.py` (`WeatherAgent`, Open-Meteo `/v1/forecast`), keeping `WeatherAgent.get_weather(latitude, longitude) -> dict` intact while supporting current observations, hourly sub-day forecast windows, daily forecasts up to 16 days ahead, and Open-Meteo geocoding.
3. **Graceful Degradation**: Weather or network failures never break voice transcription, transcript editing, TTS audio feedback, or `POST /api/understand`. Unavailable weather states are represented explicitly with `available: false` and a typed `status` code rather than fabricated weather values.

---

## 📍 Location Resolution Priority

`LocationResolver` (`fashion_stt/weather_context.py`) resolves geographic locations strictly in priority order:

1. **Explicit Geographic Location in Current User Request (`source = "request"`)**  
   Extracted cities/places in the spoken or typed request (e.g., *"I need an outfit for tomorrow morning in Boston"*). Non-geographic venue descriptors (*"outdoor"*, *"office"*, *"restaurant"*, *"beach"*, *"campus"*, *"rooftop"*) are preserved on `FashionRequestOutput.location` for downstream reasoning without being misinterpreted as city names.
2. **Explicit Application / Request Setting (`source = "settings"` or `"coordinates"`)**  
   Optional `location` or `(latitude, longitude)` supplied on the request payload, configured via `WEATHER_DEFAULT_LOCATION` / `WEATHER_DEFAULT_LATITUDE` + `WEATHER_DEFAULT_LONGITUDE`, or supplied by a modular `fallback_provider` callable hook ready for future User Profile Module integration.
3. **Unavailable (`status = "missing_location"`, `available = false`)**  
   If neither source provides a geographic location, no fallback city or IP guess is ever invented.

---

## 🕒 Time & Forecast Selection

- **Unspecified time (`null`) / `"now"`**: Queries Open-Meteo current observations (`mode = "current"`, sets `observed_at`).
- **Same-day or future sub-day windows** (*"this morning"*, *"this afternoon"*, *"tonight"*, *"tomorrow morning"*): Queries Open-Meteo hourly forecast series for the exact local hour window (`08:00–11:00`, `12:00–17:00`, `18:00–21:00`) on the resolved target date (`mode = "forecast"`, sets `forecast_for`, e.g., `"2026-10-24 morning"`).
- **Whole-day future dates** (*"tomorrow"*, *"this Saturday"*, *"this weekend"*, `"YYYY-MM-DD"`): Queries Open-Meteo daily & hourly forecast summaries (`mode = "forecast"`, sets `forecast_for`, `temperature_range`, `precipitation_probability`).
- **Out-of-range dates** (past dates or dates `> 16` days ahead such as *"next month"* or `"2026-12-20"`): Returns `available = false`, `status = "unsupported_forecast_date"` without silently substituting current weather conditions.

---

## 📡 Backend API & Data Contracts

Authentication: None required (local/service API; CORS enabled).

### 1. `POST /api/understand`
Processes typed or transcribed spoken requests and returns separated user request and weather contexts.

**Request Body (`UnderstandRequest`):**
```json
{
  "text": "I need an outfit for tomorrow morning in Boston.",
  "session_id": "session_a1b2c3d4",
  "input_method": "text",
  "raw_transcript": null,
  "location": null,
  "latitude": null,
  "longitude": null
}
```

**Response Body (`UnderstandResponse`):**
- `structured_data`: `FashionRequestOutput` (user request features only)
- `weather_context`: `WeatherContext` (environmental weather context only)
- `recommendation_context`: `RecommendationContext` (`{ "request_context": ..., "weather_context": ... }`)
- `assistant_response`, `tts_url`, `session_id`, `turn_index`

### 2. `GET /api/weather`
Standalone environmental weather endpoint.

**Query Parameters:**
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `location` | `string` | Conditional | City/region name (e.g., `"Boston"`) or `"lat, lon"` string. Required unless coordinates or `WEATHER_DEFAULT_LOCATION` are set. |
| `latitude` | `float` | Conditional | Latitude in `[-90.0, 90.0]` (must be paired with `longitude`). |
| `longitude` | `float` | Conditional | Longitude in `[-180.0, 180.0]` (must be paired with `latitude`). |
| `date_or_time` | `string` | Optional | ISO date (`"2026-10-24"`), date + window (`"2026-10-24 morning"`), or relative phrase (`"this afternoon"`, `"this Saturday"`). |

**Response Schema (`WeatherContext`):**
```json
{
  "available": true,
  "status": "ok",
  "mode": "forecast",
  "message": null,
  "location": {
    "name": "Boston",
    "latitude": 42.3601,
    "longitude": -71.0589,
    "country": "United States",
    "timezone": "America/New_York",
    "source": "request"
  },
  "observed_at": null,
  "forecast_for": "2026-10-24 morning",
  "temperature": { "value": 9.5, "unit": "C" },
  "temperature_range": { "min": 8.5, "max": 11.0, "unit": "C" },
  "feels_like": { "value": 7.5, "unit": "C" },
  "condition": "light_rain",
  "humidity": { "value": 0.8, "unit": "ratio" },
  "precipitation": { "value": 2.5, "unit": "mm" },
  "precipitation_probability": 65.0,
  "wind_speed": { "value": 14.0, "unit": "km/h" },
  "agent_metrics": {
    "temp": 9.5,
    "humidity": 0.8,
    "precipitation": 0.025,
    "wind_speed": 14.0
  },
  "source": "open-meteo",
  "cached": false,
  "fetched_at": "2026-10-23T13:20:00Z",
  "cache_expires_at": "2026-10-23T13:30:00Z"
}
```

### Units & Explicit Error States
- **Units**: Temperature & Feels-Like in `"C"` (Celsius), Wind Speed in `"km/h"`, Precipitation amount in `"mm"`, Humidity normalized ratio in `[0.0, 1.0]` (`unit: "ratio"`, matching `WeatherAgent.get_weather()`), Forecast Precipitation Probability in `[0.0, 100.0]` (`%`). Note: Open-Meteo `/v1/forecast` does not provide government weather alerts, so alert fields are never fabricated.
- **Status Codes (`WeatherContext.status`)**:
  - `"ok"` — Fresh or valid cached weather data available (`available: true`)
  - `"missing_location"` — No geographic location supplied in request or settings
  - `"invalid_location"` — Out-of-bounds coordinates or unrecognized place name
  - `"unsupported_forecast_date"` — Past date, date `> 16` days out, or unparseable temporal expression
  - `"timeout"` — Upstream weather request timed out
  - `"network_error"` — Upstream connection/TLS failure
  - `"rate_limited"` — Provider returned HTTP `429`
  - `"invalid_credentials"` — Provider rejected API key (`401`/`403`)
  - `"invalid_response"` — Non-JSON or malformed field types
  - `"missing_weather_fields"` — Required provider weather fields missing or null

---

## ⚙️ Environment Variables & Caching

Open-Meteo's free forecast and geocoding endpoints require **no API key**. Optional environment variables (documented in `.env.example`):

- `PORT` (default `8000`): FastAPI HTTP/WebSocket server port.
- `WEATHER_API_BASE_URL` (default `https://api.open-meteo.com/v1/forecast`): Forecast & current observation endpoint.
- `WEATHER_GEOCODING_URL` (default `https://geocoding-api.open-meteo.com/v1/search`): Place geocoding endpoint.
- `WEATHER_API_KEY` (optional, unset by default): Commercial Open-Meteo API key if used; never hardcoded or exposed to frontend clients.
- `WEATHER_API_TIMEOUT` (default `10`): HTTP request timeout in seconds (`WeatherAgent()` direct default remains `15`).
- `WEATHER_CACHE_TTL_SECONDS` (default `600`): TTL in seconds for bounded thread-safe in-memory `WeatherCache` (`0` disables caching; expired entries are evicted immediately and never served as live weather).
- `WEATHER_CACHE_MAX_SIZE` (default `128`): Maximum cached `(lat, lon, mode, window)` entries.
- `WEATHER_MAX_FORECAST_DAYS` (default `16`): Supported Open-Meteo forecast horizon in days.
- `WEATHER_TIMEZONE` (default `auto`): Provider timezone resolution setting.
- `WEATHER_DEFAULT_LOCATION` / `WEATHER_DEFAULT_LATITUDE` / `WEATHER_DEFAULT_LONGITUDE` (unset by default): Optional explicit deployment fallback location.

---

## 🚀 Running & Verifying the Application

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Launch the web application & API server
python run_server.py
```

Open **`http://localhost:8000`** in your browser.

### Running Automated Tests

```bash
# Run full unit, STT WER evaluation, NLU evaluation, and weather integration suite:
python -m unittest discover -v tests
# or with pytest:
pytest -v
```

- **Mocked unit & pipeline integration tests** (`TestMockedWeatherModuleIntegration` + all existing STT/NLU suites) run deterministically offline without external network dependencies.
- **Live Open-Meteo provider integration test** (`TestLiveOpenMeteoProviderIntegration`) automatically executes against `https://api.open-meteo.com/v1/forecast` whenever outbound internet access to Open-Meteo is reachable, and skips cleanly with an explicit notice in network-isolated sandboxes.
