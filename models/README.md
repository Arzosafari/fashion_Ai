# Vosk Speech Recognition Models

This directory holds the acoustic model for English Speech-to-Text processing.

- **Default Model:** `vosk-model-small-en-us-0.15` (Lightweight ~40MB compressed, ~68MB uncompressed).
- **Automatic Setup:** If not present locally, the application automatically downloads and extracts the model on first launch via `fashion_stt.engine.download_model()`.
- **Manual Setup:** You can also download it directly from [Alphacephei Vosk Models](https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip) and extract it into this folder.
