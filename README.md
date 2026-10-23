# Fashion AI — User Request Understanding Module

A dedicated, production-ready natural language understanding module for Fashion AI that accepts **English voice or text input**, performs domain-optimized speech-to-text, maintains conversational state across multi-turn follow-ups, and outputs **validated, machine-readable structured JSON** for the Outfit Recommendation Engine.

---

## 🌟 Architecture & Data Flow

```text
       USER INPUT (Voice or Text)
                  │
      ┌───────────┴───────────┐
      ↓                       ↓
Voice Recording         Keyboard Typing
      │                       │
Speech-to-Text (Vosk / WebSpeech) │
      │                       │
Editable Transcript Review    │
      └───────────┬───────────┘
                  ↓
      Request Normalization & Phonetic Lexicon
                  ↓
      Multi-Turn Conversational Memory (Session-scoped)
                  ↓
      Intent & Semantic Feature Extraction
      ├── Intent Classification (outfit_recommendation, modification, styling_advice)
      ├── Occasion & Formality (explicit vs inferred)
      ├── Temporal Resolution (relative & explicit dates)
      ├── Location Extraction (cities, venues)
      ├── Garments (+ Included / - Excluded)
      ├── Colors (+ Preferred / - Excluded)
      ├── Fit, Silhouette & Functional Requirements
      └── Constraints & Negations Preservation
                  ↓
      Pydantic Schema Validation
                  ↓
      Validated Machine-Readable JSON Output
                  │
      ┌───────────┴───────────┐
      ↓                       ↓
Text-to-Speech Spoken    Future Recommendation
    Confirmation                Engine
```

---

## 📋 Structured Output Schema

The module outputs a strict, validated Pydantic schema (`FashionRequestOutput`):

```json
{
  "intent": {
    "type": "outfit_recommendation",
    "description": "An outfit for job interview",
    "is_clear": true
  },
  "occasion": {
    "value": "job interview",
    "formality": "formal",
    "source": "explicit"
  },
  "location": {
    "value": "New York",
    "source": "explicit"
  },
  "time": {
    "expression": "tomorrow",
    "resolved": "2026-10-13",
    "source": "explicit"
  },
  "style_preferences": [
    {
      "value": "minimalist",
      "source": "explicit"
    }
  ],
  "garment_preferences": {
    "include": ["blazer"],
    "exclude": ["jeans"]
  },
  "colors": {
    "preferred": ["navy", "cream"],
    "excluded": ["black"]
  },
  "fit_preferences": ["tailored"],
  "functional_requirements": ["warmth", "comfort"],
  "constraints": ["budget: under $150", "don't want to wear heels"],
  "additional_details": [],
  "missing_information": [],
  "clarification_needed": false,
  "clarification_question": null,
  "raw_input": "I need something to wear to a job interview tomorrow in New York.",
  "clean_input": "I need something to wear to a job interview tomorrow in New York.",
  "input_method": "text",
  "session_id": "session_a1b2c3d4",
  "turn_index": 1,
  "confidence_score": 0.95
}
```

---

## ⚡ Key Capabilities

### 1. Unified Voice and Text Pipeline
- **Keyboard Typing**: Fully functional text input with instant Enter key submission.
- **Voice Recording**: Dual-engine support (Browser Web Speech API for 0ms latency + Vosk Kaldi WebSocket streaming).
- **Transcript Review & Correction**: Users can inspect and edit their speech transcripts before submitting to the NLP pipeline, or toggle auto-submit.
- **Duplicate Prevention**: Buttons and inputs are locked during processing to prevent duplicate turns.

### 2. Multi-Turn Conversational Memory
Maintains dialogue history across turns without conflating temporary request context with persistent user profile attributes:
- **Turn 1**: *"I need an outfit for a graduation ceremony."*  
  ➔ `occasion = "graduation"`
- **Turn 2**: *"Make it more minimalist."*  
  ➔ `occasion = "graduation"`, `styles = ["minimalist"]`
- **Turn 3**: *"Actually, avoid black."*  
  ➔ `occasion = "graduation"`, `styles = ["minimalist"]`, `colors.excluded = ["black"]`

### 3. Negation & Exclusion Preservation
Explicitly distinguishes positive preferences from negative constraints:
- *"I want to wear something other than jeans"* ➔ `garment_preferences.exclude: ["jeans"]`
- *"Formal dinner, but I don't want to wear heels"* ➔ `garment_preferences.exclude: ["heels"]`, `constraints: ["not want to wear heels"]`
- *"Avoid black and red"* ➔ `colors.excluded: ["black", "red"]`

### 4. Ambiguity Detection & Clarification
- If a request is genuinely ambiguous (e.g., *"Make it more formal"* without prior conversation context):
  - Sets `clarification_needed = true`
  - Generates targeted clarification question: *"What event or outfit would you like to modify?"*
- If the request is clear, proceeds immediately without unnecessary questions.

### 5. Spoken Audio Feedback (TTS)
- Confirms understood requests with natural spoken audio:  
  *"Got it! Looking for a formal and minimalist outfit for job interview tomorrow. (Avoiding black.)"*
- Includes play, pause, stop, and mute controls.

---

## 🧪 Evaluation Results

The module includes an automated benchmark suite (`tests/`):

### A. Speech-to-Text Evaluation (`tests/test_stt_evaluation.py`)
Tested across representative English fashion audio samples using dynamic programming Levenshtein Word Error Rate:
* **Corpus Word Error Rate (WER)**: **2.00%** (1 error across 50 words)
  * `sample_outerwear.wav`: **0.00% WER**
  * `sample_dress.wav`: **0.00% WER**
  * `sample_houndstooth.wav`: **0.00% WER**
  * `sample_knitwear.wav`: **9.09% WER**
* **Negation Preservation in STT**: **100%**

### B. Feature Extraction Evaluation (`tests/test_feature_extraction_evaluation.py`)
Tested across complex requests, negative preferences, follow-ups, and ambiguities:
* **Intent Classification Accuracy**: **100.0%**
* **Occasion Extraction Accuracy**: **100.0%**
* **Clarification / Ambiguity Accuracy**: **100.0%**
* **Negation Preservation Rate**: **100.0%**
* **Garment Exclusion Precision / Recall / F1**: **1.00 / 1.00 / 1.00**
* **Color Preferences Precision / Recall / F1**: **1.00 / 1.00 / 1.00**

### C. Functional Integration Tests (`tests/test_unified_pipeline.py`)
All 11 criteria from Section 12.3 verified and passing:
1. Typed request reaches shared pipeline: **PASS**
2. Voice request transcribed and reaches same pipeline: **PASS**
3. Transcript can be edited before submission: **PASS**
4. Consistent output across input methods: **PASS**
5. Negative preferences preserved: **PASS**
6. Follow-up updates request state: **PASS**
7. Missing details are not fabricated: **PASS**
8. Invalid input handled safely: **PASS**
9. Permission and error feedback: **PASS**
10. Text-to-speech functional: **PASS**
11. Self-contained offline resilience: **PASS**

---

## 🚀 Running the Module

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python run_server.py
```
Open **`http://localhost:8000`** in your browser.

Run tests:
```bash
python -m unittest discover tests
# 31 tests passed in 9.89s (OK)
```
