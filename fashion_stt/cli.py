"""
Command Line Interface for Fashion AI Request Understanding & Weather Context
Usage:
    fashion-stt --file audio.wav
    fashion-stt --text "I want a hound tooth blazer for tomorrow in Boston"
    fashion-stt --weather "Boston" --date "tomorrow morning"
    fashion-stt --serve --port 8000
"""

import argparse
import json
from .engine import RealtimeTranscriber
from .extractor import FashionEntityExtractor
from .weather_context import ContextIntegrator, WeatherContextService


def main():
    parser = argparse.ArgumentParser(
        description="Fashion AI: Real-time English Speech-to-Text, Feature Extraction & Weather Context"
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
        help="Run fashion phonetic correction, feature extraction, and context integration on text."
    )
    group.add_argument(
        "--weather", "-w",
        type=str,
        help="Query environmental weather context directly for a location (e.g., 'Boston')."
    )
    group.add_argument(
        "--serve", "-s",
        action="store_true",
        help="Start the FastAPI real-time streaming WebSocket & REST server."
    )

    parser.add_argument(
        "--location",
        type=str,
        default=None,
        help="Optional fallback location setting when using --text."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Optional forecast date or period when using --weather (e.g. '2026-10-24', 'tomorrow morning')."
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
        print(f"👗 Launching Fashion AI Server on http://{args.host}:{args.port}")
        uvicorn.run("fashion_stt.server:app", host=args.host, port=args.port, reload=False)
        return

    if args.weather is not None:
        service = WeatherContextService()
        ctx = service.get_weather_context(location=args.weather, date_or_time=args.date)
        print(json.dumps(ctx.model_dump(), indent=2))
        return

    if args.text:
        extractor = FashionEntityExtractor()
        req = extractor.extract(args.text)
        integrator = ContextIntegrator(WeatherContextService())
        combined = integrator.build_context(req, fallback_location=args.location)
        print(json.dumps(combined.model_dump(), indent=2))
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
