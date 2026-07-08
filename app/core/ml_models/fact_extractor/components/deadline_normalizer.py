from datetime import datetime, time, timezone
from typing import List, Dict, Any
import dateparser

class DeadlineNormalizer:
    IMMEDIATE_CUES = {"immediately", "right now", "asap", "urgently", "as soon as possible"}
    TIME_MODIFIERS = ["morning", "afternoon", "evening", "night", "this", "by"]
    RECURRING_MARKERS = ["monthly", "weekly", "daily"]

    @classmethod
    def normalize_deadlines(cls, facts: List[Dict[str, Any]], anchor_date: datetime | None = None) -> List[Dict[str, Any]]:
        """
        Enriches facts with absolute calendar target dates resolved from temporal hints/entities.
        Stores 'parsed_deadline' in the fact's payload.
        """
        base_now = anchor_date or datetime.now(timezone.utc)
        
        for fact in facts:
            fact_type = fact.get("fact_type", "fact")
            if fact_type not in {"task", "commitment"}:
                continue

            payload = fact.get("payload", {})
            source_sentence = fact.get("source_sentence", "").lower()
            
            # Step 1: Check immediate cues
            if any(cue in source_sentence for cue in cls.IMMEDIATE_CUES):
                payload["parsed_deadline"] = base_now.isoformat()
                payload["raw_temporal_hint"] = "immediate"
                continue

            raw_entities = payload.get("entities", {})
            # Look for DATE or TIME entities in the spacy entities extracted
            date_ents = raw_entities.get("DATE", []) + raw_entities.get("TIME", [])
            if not date_ents:
                # Check raw_temporal_hint if it was pre-extracted
                hint = payload.get("raw_temporal_hint")
                if hint:
                    date_ents = [hint]

            resolved_dt = None
            for ent_text in date_ents:
                raw_text = ent_text.lower().strip()
                if any(marker in raw_text for marker in cls.RECURRING_MARKERS):
                    continue

                preference = "past" if "last" in raw_text else "future"
                parse_target_text = raw_text
                for word in cls.TIME_MODIFIERS:
                    parse_target_text = parse_target_text.replace(word, "").strip()

                if not parse_target_text:
                    parse_target_text = "today"

                parsed_dt = dateparser.parse(
                    parse_target_text,
                    languages=['en'],
                    settings={
                        'PREFER_DATES_FROM': preference,
                        'RELATIVE_BASE': base_now.replace(tzinfo=None), # dateparser doesn't like tz-aware bases sometimes
                        'PREFER_DAY_OF_MONTH': 'current'
                    }
                )

                if parsed_dt:
                    resolved_dt = datetime.combine(parsed_dt.date(), time.min).replace(tzinfo=timezone.utc)
                    payload["raw_temporal_hint"] = ent_text
                    break

            if resolved_dt:
                payload["parsed_deadline"] = resolved_dt.isoformat()
            else:
                payload["parsed_deadline"] = None

        return facts
