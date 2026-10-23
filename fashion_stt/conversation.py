"""
Conversation State Manager for Fashion AI User Request Understanding Module
Maintains multi-turn context, resolves follow-up modifications, merges exclusions,
and generates coherent natural-language confirmations for the user.
"""

import uuid
import re
from typing import Dict, List, Optional, Tuple, Any
from copy import deepcopy

from .extractor import FashionEntityExtractor
from .models import (
    FashionRequestOutput,
    IntentModel,
    OccasionModel,
    LocationModel,
    TimeModel,
    StylePreferenceItem,
    GarmentPreferencesModel,
    ColorPreferencesModel
)


class ConversationSession:
    """Represents an active multi-turn fashion request conversation session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turn_index = 0
        self.history: List[Dict[str, Any]] = []
        self.active_request: Optional[FashionRequestOutput] = None

    def add_turn(
        self,
        user_input: str,
        input_method: str,
        assistant_response: str,
        structured_output: FashionRequestOutput
    ):
        self.turn_index += 1
        self.history.append({
            "turn": self.turn_index,
            "user_input": user_input,
            "input_method": input_method,
            "assistant_response": assistant_response,
            "structured_output": structured_output.model_dump()
        })
        self.active_request = structured_output


class ConversationManager:
    """
    Manages conversational memory across multiple turns for fashion requests.
    Supports follow-up instructions, corrections, preference updates, and ambiguity recovery.
    """

    def __init__(self, extractor: Optional[FashionEntityExtractor] = None):
        self.extractor = extractor or FashionEntityExtractor()
        self.sessions: Dict[str, ConversationSession] = {}

    def get_or_create_session(self, session_id: Optional[str] = None) -> ConversationSession:
        if not session_id or session_id not in self.sessions:
            new_id = session_id or str(uuid.uuid4())
            session = ConversationSession(new_id)
            self.sessions[new_id] = session
            return session
        return self.sessions[session_id]

    def reset_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def process_request(
        self,
        text: str,
        session_id: Optional[str] = None,
        input_method: str = "text",
        raw_transcript: Optional[str] = None
    ) -> Tuple[FashionRequestOutput, str, str]:
        """
        Executes the unified request-understanding pipeline.
        Merges multi-turn conversational updates when applicable.
        
        Returns:
            (structured_output, assistant_response, active_session_id)
        """
        session = self.get_or_create_session(session_id)
        
        # 1. Extract fresh features from the current utterance
        fresh_extraction = self.extractor.extract(
            text=text,
            input_method=input_method,
            raw_transcript=raw_transcript
        )

        # 2. Check if this is a follow-up modification to an existing active request
        if session.active_request is not None:
            merged_output = self._merge_follow_up(session.active_request, fresh_extraction, text)
        else:
            merged_output = fresh_extraction

        # Update turn metadata
        merged_output.session_id = session.session_id
        merged_output.turn_index = session.turn_index + 1
        merged_output.input_method = input_method
        merged_output.raw_input = raw_transcript or text

        # 3. Generate natural conversational confirmation / clarification response
        assistant_response = self._generate_assistant_response(merged_output)

        # 4. Save to session history
        session.add_turn(
            user_input=text,
            input_method=input_method,
            assistant_response=assistant_response,
            structured_output=merged_output
        )

        return merged_output, assistant_response, session.session_id

    def _merge_follow_up(
        self,
        previous: FashionRequestOutput,
        fresh: FashionRequestOutput,
        raw_text: str
    ) -> FashionRequestOutput:
        """
        Intelligently merges a follow-up modification with the active request state.
        For example:
          Turn 1: "I need an outfit for a graduation ceremony."
          Turn 2: "Make it more minimalist." -> Adds style: minimalist, keeps graduation!
          Turn 3: "Actually, avoid black." -> Adds black to excluded colors!
        """
        lower = raw_text.lower()
        is_fresh_request = bool(re.search(
            r"\b(start\s+over|never\s*mind|new\s+outfit|forget\s+that|instead\s+of\s+that\s+i\s+need)\b", 
            lower
        ))
        
        if is_fresh_request and fresh.occasion.value:
            # User wants a completely new request
            return fresh

        # Clone previous state as the base
        merged = previous.model_copy(deep=True)

        # 1. Update Intent
        if fresh.intent.type in ("modification", "alternative_request", "clarification_response"):
            merged.intent.type = fresh.intent.type
            merged.intent.description = f"{previous.intent.description} ({fresh.intent.description})"
            merged.intent.is_clear = True
            merged.clarification_needed = False
            merged.clarification_question = None

        # 2. Update Occasion (if explicitly provided in follow-up)
        if fresh.occasion.value:
            merged.occasion = fresh.occasion

        # 3. Update Location (if explicitly provided in follow-up)
        if fresh.location.value:
            merged.location = fresh.location

        # 4. Update Time (if explicitly provided in follow-up)
        if fresh.time.resolved:
            merged.time = fresh.time

        # 5. Update Style Preferences
        if fresh.style_preferences:
            existing_styles = {s.value.lower() for s in merged.style_preferences}
            for st in fresh.style_preferences:
                if st.value.lower() not in existing_styles:
                    merged.style_preferences.append(st)

        # 6. Update Garments (Add included, remove any newly excluded)
        if fresh.garment_preferences.exclude:
            for g in fresh.garment_preferences.exclude:
                if g not in merged.garment_preferences.exclude:
                    merged.garment_preferences.exclude.append(g)
                # Remove from include if it was previously included
                if g in merged.garment_preferences.include:
                    merged.garment_preferences.include.remove(g)

        if fresh.garment_preferences.include:
            for g in fresh.garment_preferences.include:
                if g not in merged.garment_preferences.include and g not in merged.garment_preferences.exclude:
                    merged.garment_preferences.include.append(g)

        # 7. Update Colors (Add preferred, remove newly excluded)
        if fresh.colors.excluded:
            for c in fresh.colors.excluded:
                if c not in merged.colors.excluded:
                    merged.colors.excluded.append(c)
                # Remove from preferred if previously preferred
                if c in merged.colors.preferred:
                    merged.colors.preferred.remove(c)

        if fresh.colors.preferred:
            for c in fresh.colors.preferred:
                if c not in merged.colors.preferred and c not in merged.colors.excluded:
                    merged.colors.preferred.append(c)

        # 8. Update Fit Preferences
        for fit in fresh.fit_preferences:
            if fit not in merged.fit_preferences:
                merged.fit_preferences.append(fit)

        # 9. Update Functional Requirements
        for func in fresh.functional_requirements:
            if func not in merged.functional_requirements:
                merged.functional_requirements.append(func)

        # 10. Update Constraints
        for con in fresh.constraints:
            if con not in merged.constraints:
                merged.constraints.append(con)

        return merged

    def _generate_assistant_response(self, structured: FashionRequestOutput) -> str:
        """Generates a clear, natural conversational response confirming what was understood."""
        if structured.clarification_needed and structured.clarification_question:
            return structured.clarification_question

        parts = []

        # Styles
        if structured.style_preferences:
            styles_str = " and ".join(s.value for s in structured.style_preferences)
            parts.append(f"{styles_str}")

        # Garments
        if structured.garment_preferences.include:
            garments_str = ", ".join(structured.garment_preferences.include)
            parts.append(f"{garments_str}")
        else:
            parts.append("outfit")

        # Occasion
        if structured.occasion.value:
            parts.append(f"for {structured.occasion.value}")

        # Location
        if structured.location.value:
            parts.append(f"in {structured.location.value}")

        # Time
        if structured.time.expression:
            parts.append(f"{structured.time.expression}")

        core_msg = " ".join(parts).strip()
        response = f"Got it! Looking for a {core_msg}."

        # Add exclusions / constraints
        exclusions = []
        if structured.colors.excluded:
            exclusions.append(f"avoiding {' and '.join(structured.colors.excluded)}")
        if structured.garment_preferences.exclude:
            exclusions.append(f"excluding {' and '.join(structured.garment_preferences.exclude)}")
        if structured.functional_requirements:
            exclusions.append(f"prioritizing {' and '.join(structured.functional_requirements)}")

        if exclusions:
            response += f" ({', '.join(exclusions).capitalize()}.)"

        return response
