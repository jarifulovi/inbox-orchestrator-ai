import html
import re
import unicodedata
from typing import List

from app.schemas.extracted_actions import ExtractedActionPrediction

try:
    import contractions as contractions_lib
except ImportError:  # pragma: no cover - graceful fallback if dependency is unavailable
    contractions_lib = None


class TextPreprocessor:
    # Stage 1: Structural email cleanup. Keep this focused on format/noise only.
    STRUCTURAL_REMOVALS = (
        r"(?im)^\s*(from|sent|to|cc|bcc|subject|date)\s*:\s*.*$",
        r"(?im)^\s*on .+wrote:\s*$",
        r"(?im)^\s*[-_ ]*forwarded message[-_ ]*$",
    )

    # Stage 3: Syntactic normalization for downstream rule-based extraction.
    SYNTACTIC_CLEANERS = (
        (r"\bmake sure you\b", "please"),
        (r"\bmake sure to\b", "please"),
        (r"\bkindly ensure(?: that)? you\b", "please"),
        (r"\bkindly\b", "please"),
        (r"\bi need you to\b", "please"),
        (r"\bi need to\b", "please"),
        (r"\bwe need you to\b", "please"),
        (r"\bwe need to\b", "please"),
        (r"\bwould you please\b", "please"),
        (r"\bcould you please\b", "please"),
        (r"\bcan you please\b", "please"),
        (r"\bwould you\b", "please"),
        (r"\bcould you\b", "please"),
        (r"\bcan you\b", "please"),
        (r"\bplease could you\b", "please"),
        (r"\bplease can you\b", "please"),
        (r"\bwhen you get a chance\b", "please"),
        (r"\bwhen you have a moment\b", "please"),
        (r"\bif you can\b", "please"),
        (r"\bif possible\b", "please"),
        (r"\bi would like you to\b", "please"),
        (r"\bi would appreciate it if you could\b", "please"),
        (r"\bplease be advised to\b", "please"),
        (r"\bplease note that you\b", "please"),
        (r"\bexpect you to\b", "please"),
        (r"\byou need to\b", "please"),
        (r"\byou should\b", "please"),
        (r"\byou must\b", "please"),
        (r"\byou have to\b", "please"),
        (r"\bwe should\b", "please"),
        (r"\bwe must\b", "please"),
        (r"\bby eod\b", "by end of day"),
        (r"\bbefore eod\b", "by end of day"),
        (r"\beod\b", "end of day"),
        (r"\bbefore cob\b", "by end of day"),
        (r"\bby end of day\b", "by end of day"),
        (r"\bbefore end of day\b", "by end of day"),
        (r"\bat your earliest convenience\b", "as soon as possible"),
        (r"\bas soon as possible\b", "as soon as possible"),
        (r"\basap\b", "as soon as possible"),
        (r"\bsometime today\b", "today"),
    )

    _FALLBACK_CONTRACTIONS = (
        (r"\bcan't\b", "cannot"),
        (r"\bwon't\b", "will not"),
        (r"\bn't\b", " not"),
        (r"\bI'm\b", "I am"),
        (r"\bI've\b", "I have"),
        (r"\bI'll\b", "I will"),
        (r"\bwe're\b", "we are"),
        (r"\bthat's\b", "that is"),
        (r"\bit's\b", "it is"),
        (r"\bthere's\b", "there is"),
        (r"\byou're\b", "you are"),
        (r"\bwe've\b", "we have"),
        (r"\bdon't\b", "do not"),
        (r"\bdoesn't\b", "does not"),
        (r"\bdidn't\b", "did not"),
        (r"\bshouldn't\b", "should not"),
        (r"\bcouldn't\b", "could not"),
        (r"\bwouldn't\b", "would not"),
        (r"\bI'm not\b", "I am not"),
    )

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        text = re.sub(r"[\t\f\v ]+", " ", text)
        text = re.sub(r" *\n+ *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([,.;:!?])(\S)", r"\1 \2", text)
        return text.strip()

    @classmethod
    def _structural_clean(cls, text: str) -> str:
        """Stage 1: remove formatting, quoted headers, and common email noise."""
        if text is None:
            return ""

        cleaned = str(text)
        if not cleaned.strip():
            return ""

        cleaned = html.unescape(cleaned)
        cleaned = unicodedata.normalize("NFKC", cleaned)
        cleaned = cleaned.replace("\xa0", " ")
        cleaned = re.sub(r"(?is)<\s*br\s*/?\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?is)</\s*(p|div|li|tr|td|h[1-6])\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
        cleaned = re.sub(r"(?m)^\s*>+\s?", "", cleaned)

        for pattern in cls.STRUCTURAL_REMOVALS:
            cleaned = re.sub(pattern, "", cleaned)

        return cls._collapse_whitespace(cleaned)

    @classmethod
    def _expand_contractions(cls, text: str) -> str:
        """Stage 2: expand contractions using the dedicated library, with a safe fallback."""
        if not text:
            return ""

        fixer = getattr(contractions_lib, "fix", None)
        if callable(fixer):
            return str(fixer(text))

        cleaned = text
        for pattern, replacement in cls._FALLBACK_CONTRACTIONS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def _normalize_syntax(cls, text: str) -> str:
        """Stage 3: reshape conversational phrasing into more uniform action language."""
        if not text:
            return ""

        cleaned = text
        for pattern, replacement in cls.SYNTACTIC_CLEANERS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"(?i)\bplease\s*,\s*", "please ", cleaned)
        cleaned = re.sub(r"(?i)\bplease(?:\s*,?\s*please)+\b", "please", cleaned)
        return cls._collapse_whitespace(cleaned)

    @classmethod
    def clean(cls, text: str) -> str:
        """
        End-to-end preprocessing:
        1. Structural cleaning
        2. Contraction expansion
        3. Syntactic normalization
        """
        cleaned = cls._structural_clean(text)
        cleaned = cls._expand_contractions(cleaned)
        cleaned = cls._normalize_syntax(cleaned)
        return cleaned


class ActionPostprocessor:
    # Remove actions that are too casual or low-value to be treated as real corporate tasks.
    CASUAL_VERBS = {
        "read",
        "leave",
        "watch",
        "play",
        "eat",
        "go",
        "view",
    }

    @staticmethod
    def _normalize_signature_value(value: str) -> str:
        value = "" if value is None else str(value)
        value = unicodedata.normalize("NFKC", value)
        value = re.sub(r"\s+", " ", value).strip().casefold()
        return value

    @classmethod
    def _is_casual_action(cls, action: "ExtractedActionPrediction") -> bool:
        verb = cls._normalize_signature_value(getattr(action, "verb_primitive", ""))
        return bool(verb) and verb in cls.CASUAL_VERBS

    @staticmethod
    def _deduplicate_actions(actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        seen_tasks = set()
        deduplicated = []

        for action in actions:
            task_signature = (
                ActionPostprocessor._normalize_signature_value(getattr(action, "verb_primitive", "")),
                ActionPostprocessor._normalize_signature_value(getattr(action, "object_primitive", "")),
                ActionPostprocessor._normalize_signature_value(getattr(action, "source_sentence", "")),
            )
            if task_signature not in seen_tasks:
                seen_tasks.add(task_signature)
                deduplicated.append(action)

        return deduplicated

    @classmethod
    def clean(cls, actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        """Stage 1: Normalize structures and filter out low-value semantic actions safely."""
        if not actions:
            return []

        cleaned_actions: List["ExtractedActionPrediction"] = []

        for action in actions:
            # 1. Drop casual actions completely
            if cls._is_casual_action(action):
                continue

            # 2. Safe, Non-Destructive Object Sanitization
            if action.object_primitive:
                # Convert to string safely and strip whitespace
                obj_str = str(action.object_primitive).strip()

                # Suffix Safeguard: Using a pre-compiled raw regex string prevents
                # invalid escape sequence warnings completely.
                # This safely slices off clause trailing phrases.
                clean_pattern = r"\s+(?:before|after|until|so\s+that|in\s+order\s+to)\b"

                # Perform the split cleanly
                split_parts = re.split(clean_pattern, obj_str, flags=re.IGNORECASE)

                # Re-assign back the isolated core entity
                action.object_primitive = split_parts[0].strip() if split_parts else obj_str

            cleaned_actions.append(action)

        return cleaned_actions

    @staticmethod
    def deduplicate(actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        """Filters out structurally identical actions to save DB space."""
        return ActionPostprocessor._deduplicate_actions(actions)

    @classmethod
    def process(cls, actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        """End-to-end postprocessing pipeline."""
        cleaned_actions = cls.clean(actions)
        return cls._deduplicate_actions(cleaned_actions)
