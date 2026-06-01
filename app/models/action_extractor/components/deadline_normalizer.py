from datetime import datetime, time
from typing import List
import dateparser
from app.schemas.extracted_actions import ExtractedActionPrediction


class DeadlineNormalizer:
    # Urgent business keywords mapping directly to current execution time
    IMMEDIATE_CUES = {"immediately", "right now", "asap", "urgently", "as soon as possible"}

    # Generic temporal modifiers to filter out
    TIME_MODIFIERS = ["morning", "afternoon", "evening", "night", "this", "by"]
    RECURRING_MARKERS = ["monthly", "weekly", "daily"]

    @classmethod
    def normalize_action_deadlines(cls, actions: List[ExtractedActionPrediction]) -> List[ExtractedActionPrediction]:
        """
        Data Enrichment Layer: Extracts absolute calendar target dates from
        both raw text urgency cues and spaCy context entities.
        """
        for action in actions:
            # Step 1: Pre-emptively catch text-based immediate cues ("right now", "asap")
            # These don't rely on entity parsing and keep precise hour/minute resolution
            sentence_lower = action.source_sentence.lower()
            if any(cue in sentence_lower for cue in cls.IMMEDIATE_CUES):
                action.parsed_deadline = datetime.now()
                continue  # Successfully resolved this task's deadline, move to next

            # If no raw text cues match, fall back to named entity analysis
            if not action.raw_entities:
                continue

            # Step 2: Loop through discovered entity definitions
            for ent in action.raw_entities:
                if ent["label"] not in ["DATE", "TIME"]:
                    continue

                raw_text = ent["text"].lower().strip()

                # Skip non-specific recurring markers (e.g., "send updates weekly")
                if any(marker in raw_text for marker in cls.RECURRING_MARKERS):
                    continue

                # Calculate anchoring boundaries based on context timeline hints
                preference = "past" if "last" in raw_text else "future"

                # Clean conversational time modifiers so dateparser isolates the day anchor
                parse_target_text = ent["text"].lower()
                for word in cls.TIME_MODIFIERS:
                    parse_target_text = parse_target_text.replace(word, "").strip()

                # Handle empty residuals gracefully (e.g., "this afternoon" -> "")
                if not parse_target_text:
                    parse_target_text = "today"

                # Execute mathematical baseline text resolution
                parsed_dt = dateparser.parse(
                    parse_target_text,
                    languages=['en'],
                    settings={
                        'PREFER_DATES_FROM': preference,
                        'RELATIVE_BASE': datetime.now(),
                        'PREFER_DAY_OF_MONTH': 'current'
                    }
                )

                if parsed_dt:
                    # Force calendar strings to zeroed-out midnight thresholds
                    # Example: 2026-06-02 14:30:00 -> 2026-06-02 00:00:00
                    action.parsed_deadline = datetime.combine(parsed_dt.date(), time.min)
                    break  # Assigned the primary valid date, stop inspecting further entities

        return actions