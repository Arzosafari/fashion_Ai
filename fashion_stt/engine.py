"""
Fashion STT Realtime Transcription Engine
Powered by Vosk Kaldi ASR with Fashion Lexicon boosting,
streaming partial/final event dispatch, and multi-format audio transcoding.
"""

import os
import json
import subprocess
import tempfile
import threading
from typing import Generator, Dict, Any, Optional, Union, BinaryIO
import vosk

from .lexicon import correct_fashion_text, get_fashion_grammar_list
from .extractor import FashionEntityExtractor


DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models",
    "vosk-model-small-en-us-0.15"
)
CACHE_MODEL_PATH = os.path.expanduser("~/.cache/vosk-model-small-en-us-0.15")

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"


def _resolve_existing_model_path(explicit_path: Optional[str] = None) -> Optional[str]:
    candidates = [
        explicit_path,
        os.environ.get("VOSK_MODEL_PATH"),
        DEFAULT_MODEL_PATH,
        CACHE_MODEL_PATH,
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


def download_model(target_path: Optional[str] = None) -> str:
    """Downloads and extracts the Vosk small English model if missing."""
    import urllib.request
    import zipfile

    dest = target_path or DEFAULT_MODEL_PATH
    if os.path.isdir(dest):
        return dest

    parent_dir = os.path.dirname(dest)
    os.makedirs(parent_dir, exist_ok=True)
    zip_path = os.path.join(parent_dir, "vosk-model.zip")

    print(f"📥 Vosk model not found. Automatically downloading from {VOSK_MODEL_URL}...")
    urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path)
    print("📦 Extracting speech model...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(parent_dir)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    print(f"✅ Speech model ready at {dest}")
    return dest


class RealtimeTranscriber:
    """
    Real-time speech-to-text transcriber specialized for English fashion applications.
    Supports continuous PCM chunk streaming, partial transcription events,
    fashion lexicon boosting, and entity extraction.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        enable_fashion_boosting: bool = True
    ):
        self.sample_rate = sample_rate
        self.enable_fashion_boosting = enable_fashion_boosting
        resolved = _resolve_existing_model_path(model_path)
        self.model_path = resolved or model_path or DEFAULT_MODEL_PATH
        self.model: Optional[vosk.Model] = None

        vosk.SetLogLevel(-1)
        if os.path.isdir(self.model_path):
            self.model = vosk.Model(self.model_path)

        self.extractor = FashionEntityExtractor()
        self._lock = threading.Lock()

    def _ensure_model(self) -> vosk.Model:
        if self.model is not None:
            return self.model
        with self._lock:
            if self.model is not None:
                return self.model
            existing = _resolve_existing_model_path(self.model_path)
            if existing:
                self.model_path = existing
            else:
                self.model_path = download_model(self.model_path)
            self.model = vosk.Model(self.model_path)
            return self.model

    def create_recognizer(self, words: bool = True) -> vosk.KaldiRecognizer:
        """Creates a fresh Kaldi recognizer instance for a streaming session."""
        rec = vosk.KaldiRecognizer(self._ensure_model(), self.sample_rate)
        rec.SetWords(words)
        return rec

    def process_chunk(
        self, 
        recognizer: vosk.KaldiRecognizer, 
        pcm_chunk: bytes
    ) -> Dict[str, Any]:
        """
        Processes a single raw PCM 16-bit mono audio chunk.
        
        Returns:
            Dict containing:
            - type: 'partial' | 'final' | 'silence'
            - text: raw transcribed text
            - clean_text: fashion-corrected text
            - entities: fashion entities (if final or requested)
        """
        if not pcm_chunk:
            return {"type": "silence", "text": "", "clean_text": ""}

        if recognizer.AcceptWaveform(pcm_chunk):
            res_json = json.loads(recognizer.Result())
            raw_text = res_json.get("text", "").strip()
            if raw_text:
                clean_text, corrections = correct_fashion_text(raw_text)
                return {
                    "type": "final",
                    "text": raw_text,
                    "clean_text": clean_text,
                    "corrections": corrections
                }
            return {"type": "silence", "text": "", "clean_text": ""}
        else:
            partial_json = json.loads(recognizer.PartialResult())
            partial_text = partial_json.get("partial", "").strip()
            if partial_text:
                clean_partial, _ = correct_fashion_text(partial_text)
                return {
                    "type": "partial",
                    "text": partial_text,
                    "clean_text": clean_partial
                }
            return {"type": "silence", "text": "", "clean_text": ""}

    def finalize_stream(self, recognizer: vosk.KaldiRecognizer) -> Dict[str, Any]:
        """Flushes remaining audio in recognizer at end of streaming session."""
        final_json = json.loads(recognizer.FinalResult())
        raw_text = final_json.get("text", "").strip()
        if raw_text:
            clean_text, corrections = correct_fashion_text(raw_text)
            return {
                "type": "final",
                "text": raw_text,
                "clean_text": clean_text,
                "corrections": corrections
            }
        return {
            "type": "final",
            "text": "",
            "clean_text": "",
            "corrections": []
        }

    def transcribe_file(self, file_path_or_bytes: Union[str, bytes]) -> Dict[str, Any]:
        """
        Transcribes an entire audio file (MP3, WAV, WebM, OGG, M4A, etc.)
        converting to 16kHz mono PCM via wave or ffmpeg if necessary.
        """
        pcm_data = self._to_pcm16(file_path_or_bytes)
        rec = self.create_recognizer()

        chunk_size = 4000  # 4000 bytes = 2000 samples = 125ms at 16kHz
        full_text_parts = []

        for i in range(0, len(pcm_data), chunk_size):
            chunk = pcm_data[i:i + chunk_size]
            if rec.AcceptWaveform(chunk):
                part = json.loads(rec.Result()).get("text", "").strip()
                if part:
                    full_text_parts.append(part)

        final_part = json.loads(rec.FinalResult()).get("text", "").strip()
        if final_part:
            full_text_parts.append(final_part)

        raw_text = " ".join(full_text_parts).strip()
        clean_text, corrections = correct_fashion_text(raw_text)
        extracted = self.extractor.extract(clean_text, input_method="voice", raw_transcript=raw_text)

        # Build category mappings
        categories = list({
            self.extractor.garment_to_category.get(g, "general") 
            for g in extracted.garment_preferences.include
        })
        materials = [m for m in self.extractor.materials_sorted if m in clean_text.lower()]
        patterns = [p for p in self.extractor.patterns_sorted if p in clean_text.lower()]
        brands = [b for b in self.extractor.brands_sorted if b.lower() in clean_text.lower()]

        return {
            "raw_text": raw_text,
            "clean_text": clean_text,
            "corrections": corrections,
            "structured_data": extracted.model_dump(),
            "entities": {
                "categories": categories,
                "garments": extracted.garment_preferences.include,
                "colors": extracted.colors.preferred,
                "materials": materials,
                "styles": [s.value for s in extracted.style_preferences],
                "patterns": patterns,
                "brands": brands,
                "occasions": [extracted.occasion.value] if extracted.occasion.value else [],
                "size": None,
                "gender": None,
                "price": {"min": None, "max": None, "currency": "USD", "tag": None}
            },
            "search_query": " ".join(extracted.garment_preferences.include + extracted.colors.preferred) or clean_text,
            "confidence": extracted.confidence_score
        }

    def _to_pcm16(self, source: Union[str, bytes]) -> bytes:
        """Converts audio format into raw 16kHz mono 16-bit PCM bytes (uses native wave if possible, otherwise ffmpeg)."""
        import wave
        import io

        # 1. First attempt: Direct native Python wave reading if already 16kHz mono 16-bit WAV
        try:
            bio = io.BytesIO(source) if isinstance(source, bytes) else None
            with wave.open(bio or source, 'rb') as wf:
                if wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getframerate() == self.sample_rate:
                    return wf.readframes(wf.getnframes())
        except Exception:
            pass

        # 2. Second attempt: FFmpeg conversion for MP3, WebM, OGG, M4A, etc.
        ffmpeg_cmd = [
            "ffmpeg", "-loglevel", "error", "-y"
        ]
        
        if isinstance(source, bytes):
            ffmpeg_cmd.extend(["-i", "pipe:0"])
            input_bytes = source
        else:
            ffmpeg_cmd.extend(["-i", source])
            input_bytes = None

        ffmpeg_cmd.extend([
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "pipe:1"
        ])

        try:
            proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE if input_bytes else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout_data, stderr_data = proc.communicate(input=input_bytes)
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg error: {stderr_data.decode('utf-8', errors='ignore')}")
            return stdout_data
        except FileNotFoundError:
            # Fallback if ffmpeg is in /home/user/bin
            local_ffmpeg = "/home/user/bin/ffmpeg"
            if os.path.exists(local_ffmpeg):
                ffmpeg_cmd[0] = local_ffmpeg
                proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.PIPE if input_bytes else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout_data, stderr_data = proc.communicate(input=input_bytes)
                if proc.returncode != 0:
                    raise RuntimeError(f"FFmpeg error: {stderr_data.decode('utf-8', errors='ignore')}")
                return stdout_data
            raise RuntimeError("FFmpeg executable not found in PATH or /home/user/bin/ffmpeg")
