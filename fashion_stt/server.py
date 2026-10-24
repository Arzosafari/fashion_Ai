"""
Fashion AI User Request Understanding Module — FastAPI Server
Provides unified voice & text request understanding, multi-turn follow-up merging,
real-time speech-to-text, text-to-speech audio feedback, and structured output inspection.
"""

import os
import re
import json
import datetime
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .engine import RealtimeTranscriber
from .extractor import FashionEntityExtractor
from .conversation import ConversationManager
from .models import (
    UnderstandRequest,
    UnderstandResponse,
    FashionRequestOutput,
    WeatherContext,
    RecommendationContext,
    WeatherResolveRequest,
    WeatherResolveResponse,
    TrendContext,
)
from .weather_context import (
    ContextIntegrator,
    WeatherContextService,
)
from .tts import generate_tts_audio
from .lexicon import get_all_fashion_terms, correct_fashion_text

# ---------------------------------------------------------------------------
# Global Fashion Trend Module (integrated, optional at runtime)
# ---------------------------------------------------------------------------
# Imported defensively: the voice/text + weather modules must keep working even
# if the trend dependencies or database are unavailable.
try:
    from trend_system.api.router import api_router as trend_api_router
    from trend_system.bootstrap import bootstrap_trend_module
    from trend_system.service import get_trend_context as get_global_trend_context
    TREND_MODULE_AVAILABLE = True
    TREND_IMPORT_ERROR: Optional[str] = None
except Exception as _trend_import_error:  # pragma: no cover - depends on install
    trend_api_router = None  # type: ignore[assignment]
    bootstrap_trend_module = None  # type: ignore[assignment]
    get_global_trend_context = None  # type: ignore[assignment]
    TREND_MODULE_AVAILABLE = False
    TREND_IMPORT_ERROR = str(_trend_import_error)
    logging.getLogger("fashion_stt_server").warning(
        "Global Fashion Trend Module not available: %s", _trend_import_error
    )

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fashion_stt_server")


# Curated Fashion Catalog for live search & testing
FASHION_CATALOG = [
    {
        "id": "item-01",
        "name": "Oversized Vintage Leather Bomber Jacket",
        "category": "outerwear",
        "garment": "bomber jacket",
        "color": "black",
        "material": "leather",
        "style": ["vintage", "oversized", "streetwear"],
        "price": 149.00,
        "image": "https://images.unsplash.com/photo-1551028719-00167b16eac5?auto=format&fit=crop&w=600&q=80",
        "brand": "Atelier Noir",
        "description": "Distressed vintage lambskin bomber jacket."
    },
    {
        "id": "item-02",
        "name": "Emerald Green Silk Slip Dress",
        "category": "dresses",
        "garment": "slip dress",
        "color": "emerald",
        "material": "silk",
        "style": ["minimalist", "romantic", "quiet luxury"],
        "price": 135.00,
        "image": "https://images.unsplash.com/photo-1595777457583-95e059d581b8?auto=format&fit=crop&w=600&q=80",
        "brand": "Maison Soie",
        "description": "Mulberry silk slip dress with delicate drape."
    },
    {
        "id": "item-03",
        "name": "Tailored Houndstooth Wool Blazer",
        "category": "outerwear",
        "garment": "blazer",
        "color": "beige",
        "material": "wool",
        "style": ["tailored", "classic", "preppy", "business casual"],
        "price": 189.00,
        "image": "https://images.unsplash.com/photo-1591047139829-d91aecb6caea?auto=format&fit=crop&w=600&q=80",
        "brand": "Sartorial London",
        "description": "Heritage houndstooth wool blazer."
    },
    {
        "id": "item-04",
        "name": "Pure Cashmere Beige Turtleneck Sweater",
        "category": "tops",
        "garment": "sweater",
        "color": "beige",
        "material": "cashmere",
        "style": ["quiet luxury", "minimalist", "casual"],
        "price": 165.00,
        "image": "https://images.unsplash.com/photo-1576871337632-b9aef4c17ab9?auto=format&fit=crop&w=600&q=80",
        "brand": "Loro Studio",
        "description": "Ultra-soft Mongolian cashmere turtleneck."
    },
    {
        "id": "item-05",
        "name": "Wide-Leg Pleated Linen Trousers",
        "category": "bottoms",
        "garment": "trousers",
        "color": "ecru",
        "material": "linen",
        "style": ["relaxed fit", "minimalist", "casual"],
        "price": 89.00,
        "image": "https://images.unsplash.com/photo-1509631179647-0177331693ae?auto=format&fit=crop&w=600&q=80",
        "brand": "Linen & Coast",
        "description": "Breezy French Normandy linen trousers."
    },
    {
        "id": "item-06",
        "name": "Haute Couture Draped Chiffon Evening Gown",
        "category": "dresses",
        "garment": "evening gown",
        "color": "burgundy",
        "material": "chiffon",
        "style": ["haute couture", "romantic", "glamorous"],
        "price": 380.00,
        "image": "https://images.unsplash.com/photo-1566174053879-31528523f8ae?auto=format&fit=crop&w=600&q=80",
        "brand": "Saint Laurent Tribute",
        "description": "Pleated silk chiffon evening gown."
    },
    {
        "id": "item-07",
        "name": "High-Waist Tailored Culottes in Black",
        "category": "bottoms",
        "garment": "culottes",
        "color": "black",
        "material": "cotton",
        "style": ["tailored", "chic", "modern"],
        "price": 79.00,
        "image": "https://images.unsplash.com/photo-1584370848010-d7fe6bc767ec?auto=format&fit=crop&w=600&q=80",
        "brand": "Atelier Noir",
        "description": "Cropped wide culotte trousers."
    },
    {
        "id": "item-08",
        "name": "Balletcore Ribbed Wrap Top in Blush Pink",
        "category": "tops",
        "garment": "wrap top",
        "color": "pink",
        "material": "modal",
        "style": ["balletcore", "romantic", "casual"],
        "price": 54.00,
        "image": "https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?auto=format&fit=crop&w=600&q=80",
        "brand": "Étoile Dancewear",
        "description": "Ballet-inspired cross-front tie top."
    },
    {
        "id": "item-09",
        "name": "Classic Corduroy Trench Coat in Camel",
        "category": "outerwear",
        "garment": "trench coat",
        "color": "camel",
        "material": "corduroy",
        "style": ["vintage", "classic", "fall"],
        "price": 195.00,
        "image": "https://images.unsplash.com/photo-1544022613-e87ca75a784a?auto=format&fit=crop&w=600&q=80",
        "brand": "Heritage Trench Co.",
        "description": "Plush cotton corduroy belted trench coat."
    },
    {
        "id": "item-10",
        "name": "Jacquard Floral Evening Corset Top",
        "category": "tops",
        "garment": "corset",
        "color": "gold",
        "material": "jacquard",
        "style": ["y2k", "baroque", "romantic"],
        "price": 98.00,
        "image": "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=600&q=80",
        "brand": "Baroque Archive",
        "description": "Golden metallic floral tapestry corset."
    },
    {
        "id": "item-11",
        "name": "Chunky Leather Combat Boots",
        "category": "footwear",
        "garment": "boots",
        "color": "black",
        "material": "leather",
        "style": ["grunge", "streetwear", "edgy"],
        "price": 175.00,
        "image": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=600&q=80",
        "brand": "Tread Studio",
        "description": "Calfskin combat boots with lugged rubber platform."
    },
    {
        "id": "item-12",
        "name": "Minimalist Leather Crossbody Bag",
        "category": "accessories",
        "garment": "crossbody bag",
        "color": "tan",
        "material": "leather",
        "style": ["minimalist", "quiet luxury"],
        "price": 120.00,
        "image": "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?auto=format&fit=crop&w=600&q=80",
        "brand": "Forme Studio",
        "description": "Full-grain Italian vegetable tanned leather bag."
    }
]


def create_app(
    weather_service: Optional[WeatherContextService] = None,
    reference_date: Optional[datetime.date] = None,
    enable_trends: bool = True,
) -> FastAPI:
    trends_enabled = bool(enable_trends and TREND_MODULE_AVAILABLE)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialise the trend module (idempotent, non-destructive).

        The existing voice/text and weather modules do not depend on this; a
        failure is logged and the application keeps serving.
        """
        app.state.trend_bootstrap = None
        if trends_enabled:
            try:
                app.state.trend_bootstrap = await bootstrap_trend_module()
            except Exception as exc:  # pragma: no cover - depends on deployment
                logger.exception("Trend module bootstrap failed: %s", exc)
                app.state.trend_bootstrap = {"status": "failed", "error": str(exc)}
        yield

    app = FastAPI(
        title="Fashion AI — Request Understanding, Weather & Global Trend Context",
        description=(
            "Unified Voice & Text Input, Accurate English STT, Feature Extraction, "
            "Independent Weather Context Integration and Global Fashion Trend Context"
        ),
        version="2.2.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_cache_static_assets(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    # Global Fashion Trend API (/api/v1/trends/*, /api/v1/sources/*)
    if trends_enabled:
        app.include_router(trend_api_router, prefix="/api/v1")

    # Initialize core services cleanly decoupled from one another
    transcriber = RealtimeTranscriber()
    extractor = FashionEntityExtractor(reference_date=reference_date)
    conversation_manager = ConversationManager(extractor=extractor)
    active_weather_service = weather_service or WeatherContextService(reference_date=reference_date)
    context_integrator = ContextIntegrator(weather_service=active_weather_service)
    session_weather_snapshots: Dict[str, WeatherContext] = {}

    # Expose services on app.state for inspection & modularity
    app.state.weather_service = active_weather_service
    app.state.context_integrator = context_integrator
    app.state.conversation_manager = conversation_manager

    @app.get("/api/health")
    async def health_check():
        return {
            "status": "healthy",
            "module": "Fashion AI — Request Understanding, Weather & Global Trend Context Module",
            "version": "2.2.0",
            "language": "en",
            "model": "vosk-model-small-en-us-0.15",
            "weather_provider": "open-meteo",
            "input_methods": ["text", "voice"],
            "features": [
                "unified_pipeline",
                "negation_preservation",
                "conversational_follow_ups",
                "ambiguity_detection",
                "structured_json_schema",
                "text_to_speech",
                "weather_context",
                "global_trend_context",
            ],
            "lexicon_terms_count": len(get_all_fashion_terms()),
            "modules": {
                "request_understanding": "active",
                "weather": "active",
                "global_trends": {
                    "integrated": trends_enabled,
                    "api_prefix": "/api/v1/trends",
                    "collection_scope": "global",
                    "sources": ["vogue", "harpers_bazaar", "whowhatwear", "wgsn"],
                    "import_error": TREND_IMPORT_ERROR,
                },
            },
        }

    @app.get("/api/weather", response_model=WeatherContext)
    async def get_weather_endpoint(
        location: Optional[str] = Query(
            default=None,
            description="City/place name (e.g., 'Boston') or 'lat, lon' coordinate pair."
        ),
        latitude: Optional[float] = Query(
            default=None,
            description="Geographic latitude in degrees [-90, 90]."
        ),
        longitude: Optional[float] = Query(
            default=None,
            description="Geographic longitude in degrees [-180, 180]."
        ),
        date_or_time: Optional[str] = Query(
            default=None,
            description="Optional ISO date (YYYY-MM-DD) or natural window ('this afternoon', 'tomorrow morning', 'this Saturday')."
        ),
        date: Optional[str] = Query(
            default=None,
            description="Optional alias parameter for date_or_time."
        ),
    ):
        """
        Standalone Environmental Weather Context Endpoint.
        Retrieves validated current or forecast weather context independently of the voice/text NLU pipeline.
        """
        target_time = date_or_time if date_or_time is not None else date
        return active_weather_service.get_weather_context(
            location=location,
            date_or_time=target_time,
            latitude=latitude,
            longitude=longitude,
            location_source="coordinates" if (latitude is not None or longitude is not None) else "request",
        )

    @app.post("/api/weather/resolve", response_model=WeatherResolveResponse)
    async def resolve_weather_from_relay(payload: WeatherResolveRequest):
        """
        Validates raw Open-Meteo JSON payloads through `WeatherAgent` schema parsers,
        stores fresh entries in `WeatherCache`, and binds separated `WeatherContext` to
        the active session without modifying `FashionRequestOutput`.
        """
        weather_context = active_weather_service.resolve_from_provider_payload(
            location=payload.location,
            latitude=payload.latitude,
            longitude=payload.longitude,
            location_source=payload.location_source,
            date_or_time=payload.date_or_time,
            geocoding_payload=payload.geocoding_payload,
            provider_payload=payload.provider_payload,
        )

        recommendation_context: Optional[RecommendationContext] = None
        if payload.session_id:
            session_weather_snapshots[payload.session_id] = weather_context
            session = conversation_manager.sessions.get(payload.session_id)
            if session and session.active_request is not None:
                recommendation_context = RecommendationContext(
                    request_context=session.active_request.model_copy(deep=True),
                    weather_context=weather_context,
                )

        return WeatherResolveResponse(
            weather_context=weather_context,
            recommendation_context=recommendation_context,
        )

    @app.post("/api/understand", response_model=UnderstandResponse)
    async def understand_user_request(payload: UnderstandRequest):
        """
        Unified Request Understanding & Context Integration Endpoint.
        1. Extracts structured user request features independently via ConversationManager.
        2. Retrieves environmental weather context independently via ContextIntegrator.
        3. Returns both objects cleanly separated without mutating user preferences or transcripts.
        """
        if not payload.text or not payload.text.strip():
            raise HTTPException(status_code=400, detail="Text request cannot be empty.")

        try:
            structured_data, assistant_response, session_id = conversation_manager.process_request(
                text=payload.text,
                session_id=payload.session_id,
                input_method=payload.input_method,
                raw_transcript=payload.raw_transcript
            )

            # Build aggregated RecommendationContext without failing if weather is unavailable
            recommendation_context = context_integrator.build_context(
                structured_request=structured_data,
                fallback_location=payload.location,
                fallback_latitude=payload.latitude,
                fallback_longitude=payload.longitude,
            )
            weather_context = recommendation_context.weather_context
            session_weather_snapshots[session_id] = weather_context

            # Attach global trend context independently of weather availability.
            # Never blocks or fails the request-understanding pipeline.
            if trends_enabled:
                try:
                    raw_trend_context = await get_global_trend_context(limit=5)
                    trend_context = TrendContext.model_validate(raw_trend_context)
                    recommendation_context = recommendation_context.model_copy(
                        update={"trend_context": trend_context}
                    )
                except Exception as exc:
                    logger.warning("Global trend context unavailable: %s", exc)

            # Generate TTS URL for spoken audio feedback
            import urllib.parse
            encoded_text = urllib.parse.quote(assistant_response)
            tts_url = f"/api/tts?text={encoded_text}"

            return UnderstandResponse(
                status="success",
                session_id=session_id,
                turn_index=structured_data.turn_index,
                user_message=payload.text,
                assistant_response=assistant_response,
                structured_data=structured_data,
                weather_context=weather_context,
                recommendation_context=recommendation_context,
                tts_url=tts_url
            )
        except Exception as e:
            logger.exception("Error in request understanding pipeline")
            raise HTTPException(status_code=500, detail=f"Request understanding failed: {str(e)}")

    @app.get("/api/tts")
    async def text_to_speech(text: str = Query(..., description="Text to synthesize to speech")):
        """Synthesizes text into spoken MP3 audio."""
        try:
            audio_bytes = generate_tts_audio(text)
            return Response(content=audio_bytes, media_type="audio/mpeg")
        except Exception as e:
            logger.exception("TTS generation error")
            raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

    @app.post("/api/session/reset")
    async def reset_session(session_id: str = Query(..., description="Session ID to clear")):
        """Clears active conversational context for a given session."""
        success = conversation_manager.reset_session(session_id)
        session_weather_snapshots.pop(session_id, None)
        return {"status": "success", "session_id": session_id, "reset": success}

    @app.get("/api/session/{session_id}")
    async def get_session_history(session_id: str):
        """Retrieves conversational history and active state for a session."""
        session = conversation_manager.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        latest_weather = session_weather_snapshots.get(session_id)
        return {
            "session_id": session_id,
            "turn_count": session.turn_index,
            "history": session.history,
            "active_request": session.active_request.model_dump() if session.active_request else None,
            "weather_context": latest_weather.model_dump() if latest_weather else None,
        }

    @app.post("/api/transcribe")
    async def transcribe_audio_file(file: UploadFile = File(...)):
        """
        Upload an audio file (WAV, MP3, WebM, OGG, M4A) and get raw & cleaned transcription.
        """
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file uploaded")
        try:
            result = transcriber.transcribe_file(audio_bytes)
            return result
        except Exception as e:
            logger.exception("Error during audio file transcription")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    @app.post("/api/extract")
    async def extract_fashion_entities(payload: Dict[str, Any]):
        """Legacy entity extraction endpoint preserved for backward compatibility."""
        text = payload.get("text", "")
        clean_text, corrections = correct_fashion_text(text)
        res = extractor.extract(text)
        dump = res.model_dump()
        dump["clean_text"] = clean_text
        dump["raw_text"] = text

        # Legacy price regex check
        price_match = re.search(r"\bunder\s+\$?(\d+)", clean_text.lower())
        max_p = float(price_match.group(1)) if price_match else None

        dump["entities"] = {
            "categories": [extractor.garment_to_category.get(g, "general") for g in res.garment_preferences.include],
            "garments": res.garment_preferences.include,
            "colors": res.colors.preferred,
            "materials": [m for m in extractor.materials_sorted if m in clean_text.lower()],
            "styles": [s.value for s in res.style_preferences],
            "patterns": [p for p in extractor.patterns_sorted if p in clean_text.lower()],
            "brands": [b for b in extractor.brands_sorted if b.lower() in clean_text.lower()],
            "occasions": [res.occasion.value] if res.occasion.value else [],
            "size": None,
            "gender": None,
            "price": {"min": None, "max": max_p, "currency": "USD", "tag": None}
        }
        return dump

    @app.get("/api/catalog")
    async def get_catalog(
        q: Optional[str] = None,
        category: Optional[str] = None,
        color: Optional[str] = None,
        material: Optional[str] = None,
        style: Optional[str] = None,
        max_price: Optional[float] = None
    ):
        """Filter fashion catalog by voice or text extracted parameters."""
        results = []
        for item in FASHION_CATALOG:
            match = True
            if category and item["category"].lower() != category.lower():
                match = False
            if color and color.lower() not in item["color"].lower():
                match = False
            if material and material.lower() not in item["material"].lower():
                match = False
            if style and not any(style.lower() in s.lower() for s in item["style"]):
                match = False
            if max_price is not None and item["price"] > max_price:
                match = False
            if q:
                terms = q.lower().split()
                name_and_desc = (item["name"] + " " + item["description"] + " " + item["brand"]).lower()
                if not any(term in name_and_desc for term in terms):
                    match = False
            if match:
                results.append(item)
        return {"count": len(results), "items": results}

    @app.websocket("/ws/transcribe")
    async def websocket_realtime_transcribe(websocket: WebSocket):
        """
        WebSocket endpoint for real-time PCM audio streaming.
        Client sends raw 16kHz 16-bit mono PCM chunks.
        Server emits real-time 'partial' and 'final' events.
        """
        await websocket.accept()
        logger.info("WebSocket client connected for real-time STT")
        recognizer = transcriber.create_recognizer()

        try:
            while True:
                message = await websocket.receive()
                if "bytes" in message and message["bytes"]:
                    chunk = message["bytes"]
                    event = transcriber.process_chunk(recognizer, chunk)
                    if event["type"] in ("partial", "final"):
                        await websocket.send_text(json.dumps(event))

                elif "text" in message and message["text"]:
                    try:
                        control = json.loads(message["text"])
                        action = control.get("action")
                        if action == "finalize":
                            final_event = transcriber.finalize_stream(recognizer)
                            await websocket.send_text(json.dumps(final_event))
                            recognizer = transcriber.create_recognizer()
                        elif action == "reset":
                            recognizer = transcriber.create_recognizer()
                            await websocket.send_text(json.dumps({"type": "reset_ack"}))
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            try:
                await websocket.close()
            except Exception:
                pass

    # Mount static files for web application
    public_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
    if os.path.exists(public_dir):
        app.mount("/", StaticFiles(directory=public_dir, html=True), name="static")

    return app


app = create_app()
