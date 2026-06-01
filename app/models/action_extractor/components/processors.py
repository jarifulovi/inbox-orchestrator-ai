import re
from typing import List
from app.schemas.extracted_actions import ExtractedActionPrediction


class TextPreprocessor:
    @staticmethod
    def clean(text: str) -> str:
        """Strips HTML junk, normalizes spacing, and fixes whitespace glitches."""
        if not text:
            return ""
        cleaned = text.replace("&nbsp;", " ")
        cleaned = re.sub(r'<[^>]+>', '', cleaned)  # Strip stray HTML tags
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned)  # Collapse multiple blank lines
        return cleaned.strip()




class ActionPostprocessor:
    @staticmethod
    def deduplicate(actions: List[ExtractedActionPrediction]) -> List[ExtractedActionPrediction]:
        """Filters out structurally identical actions to save DB space."""
        seen_tasks = set()
        deduplicated = []

        for action in actions:
            # Generate a unique structural fingerprint for the action
            task_signature = (action.verb_primitive, action.object_primitive, action.source_sentence)
            if task_signature not in seen_tasks:
                seen_tasks.add(task_signature)
                deduplicated.append(action)

        return deduplicated