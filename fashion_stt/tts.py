"""
Text-to-Speech (TTS) Provider
Generates spoken audio responses confirming understood fashion requests.
Uses gTTS (Google Text-to-Speech) with in-memory caching and offline silent MP3 resilience.
"""

import hashlib
import io
import logging
from typing import Dict
from gtts import gTTS

logger = logging.getLogger("fashion_stt.tts")

# In-memory audio cache for frequent responses
_TTS_CACHE: Dict[str, bytes] = {}

# Valid MPEG-1 Layer 3 32kbps 44.1kHz mono silent frame (104 bytes per frame)
_SILENT_MP3_FRAME = b"\xff\xfb\x10\xc4" + (b"\x00" * 100)


def _offline_mp3_fallback() -> bytes:
    """Returns a valid multi-frame silent MP3 payload (~2KB) when external gTTS is unreachable."""
    return _SILENT_MP3_FRAME * 20


def generate_tts_audio(text: str, lang: str = "en") -> bytes:
    """
    Synthesizes speech audio (MP3) from text.
    Returns raw MP3 audio bytes; falls back to valid silent MP3 frames if offline.
    """
    if not text or not text.strip():
        text = "Request received."

    key = hashlib.md5(f"{lang}:{text.strip()}".encode("utf-8")).hexdigest()
    if key in _TTS_CACHE:
        return _TTS_CACHE[key]

    try:
        bio = io.BytesIO()
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.write_to_fp(bio)
        bio.seek(0)
        audio_bytes = bio.read()
        if len(_TTS_CACHE) > 100:
            _TTS_CACHE.clear()
        _TTS_CACHE[key] = audio_bytes
        return audio_bytes
    except Exception as exc:
        logger.warning("gTTS network synthesis unavailable, serving offline MP3 fallback: %s", exc)
        return _offline_mp3_fallback()
