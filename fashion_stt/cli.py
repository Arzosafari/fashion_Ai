"""
Command Line Interface for Fashion STT
Usage:
    fashion-stt --file audio.wav
    fashion-stt --text "I want a hound tooth blazer"
    fashion-stt --serve --port 8000
"""

import argparse
import sys
import json
from .engine import RealtimeTranscriber
from .extractor import FashionEntityExtractor
from .lexicon import correct_fashion_text


def main():
    parser = argparse.ArgumentParser(
        description="Fashion STT: Real-time English Speech-to-Text for Fashion Projects"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--file", "-f",
        type=str,
        help="Path to an audio file (WAV, MP3, WebM, OGG, M4A) to transcribe."
    )
    group.add_argument(
        "--text", "-t",
        type=str,
        help="Test fashion phonetic correction and entity extraction on raw text."
    )
    group.add_argument(
        "--serve", "-s",
        action="store_true",
        help="Start the FastAPI real-time streaming WebSocket & REST server."
    )

    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Port to run the server on (default: 8000)."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host address to bind (default: 0.0.0.0)."
    )

    args = parser.parse_args()

    if args.serve:
        import uvicorn
        print(f"👗 Launching Fashion STT Real-time Server on http://{args.host}:{args.port}")
        uvicorn.run("fashion_stt.server:app", host=args.host, port=args.port, reload=False)
        return

    if args.text:
        extractor = FashionEntityExtractor()
        res = extractor.extract(args.text)
        print(json.dumps(res, indent=2))
        return

    if args.file:
        print(f"🎙️ Transcribing fashion audio: {args.file}...")
        transcriber = RealtimeTranscriber()
        res = transcriber.transcribe_file(args.file)
        print("\n=== Fashion STT Results ===")
        print(json.dumps(res, indent=2))
        return


if __name__ == "__main__":
    main()
