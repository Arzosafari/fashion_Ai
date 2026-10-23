"""
Fashion AI User Request Understanding Module — FastAPI Server
Provides unified voice & text request understanding, multi-turn follow-up merging,
real-time speech-to-text, text-to-speech audio feedback, and structured output inspection.
"""

import os
import re
import json
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .engine import RealtimeTranscriber
from .extractor import FashionEntityExtractor
from .conversation import ConversationManager
from .models import UnderstandRequest, UnderstandResponse, FashionRequestOutput
from .tts import generate_tts_audio
from .lexicon import get_all_fashion_terms, correct_fashion_text

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fashion AI — User Request Understanding Module",
        description="Unified Voice & Text Input, Accurate English STT, Feature Extraction, and Structured Recommendation Output",
        version="2.0.0"
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize core services
    transcriber = RealtimeTranscriber()
    extractor = FashionEntityExtractor()
    conversation_manager = ConversationManager(extractor=extractor)

    @app.get("/api/health")
    async def health_check():
        return {
            "status": "healthy",
            "module": "User Request Understanding Module",
            "version": "2.0.0",
            "language": "en",
            "model": "vosk-model-small-en-us-0.15",
            "input_methods": ["text", "voice"],
            "features": [
                "unified_pipeline",
                "negation_preservation",
                "conversational_follow_ups",
                "ambiguity_detection",
                "structured_json_schema",
                "text_to_speech"
            ],
            "lexicon_terms_count": len(get_all_fashion_terms())
        }

    @app.post("/api/understand", response_model=UnderstandResponse)
    async def understand_user_request(payload: UnderstandRequest):
        """
        Unified Request Understanding Endpoint.
        Accepts either typed text or transcribed voice, merges multi-turn conversational context,
        extracts structured fashion features, and returns validated JSON for the recommendation engine.
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
        return {"status": "success", "session_id": session_id, "reset": success}

    @app.get("/api/session/{session_id}")
    async def get_session_history(session_id: str):
        """Retrieves conversational history and active state for a session."""
        session = conversation_manager.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session_id,
            "turn_count": session.turn_index,
            "history": session.history,
            "active_request": session.active_request.model_dump() if session.active_request else None
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
