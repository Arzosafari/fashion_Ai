"""
Text-to-Speech (TTS) Provider
Generates spoken audio responses confirming understood fashion requests.
Uses gTTS (Google Text-to-Speech) with in-memory caching.
"""

import io
import hashlib
from typing import Optional, Dict
from gtts import gTTS

# In-memory audio cache for frequent responses
_TTS_CACHE: Dict[str, bytes] = {}


def generate_tts_audio(text: str, lang: str = "en") -> bytes:
    """
    Synthesizes speech audio (MP3) from text.
    Returns raw MP3 audio bytes.
    """
    if not text or not text.strip():
        text = "Request received."

    # Cache key
    key = hashlib.md5(f"{lang}:{text.strip()}".encode("utf-8")).hexdigest()
    if key in _TTS_CACHE:
        return _TTS_CACHE[key]

    bio = io.BytesIO()
    tts = gTTS(text=text, lang=lang, slow=False)
    tts.write_to_fp(bio)
    bio.seek(0)
    audio_bytes = bio.read()

    # Store in cache (cap at 100 entries)
    if len(_TTS_CACHE) > 100:
        _TTS_CACHE.clear()
    _TTS_CACHE[key] = audio_bytes

    return audio_bytes
