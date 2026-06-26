import html
import re
import unicodedata
from typing import List

from app.core.schemas.extracted_actions import ExtractedActionPrediction

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
        r"(?im)^\s*[-*_~=]{3,}\s*$",
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
        (r"\bremember to\b", "please")
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
        url_pattern = r'https?://\S+'
        cleaned = re.sub(url_pattern, "[LINK]", cleaned)

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
    ALLOWED_ACTION_VERBS = {
        "verify", "review", "submit", "update", "approve", "confirm",
        "check", "send", "sign", "complete", "schedule", "track"
    }
    HARD_DELETE_VERBS = {
        # Original structural/helper verbs
        "let", "shall",
        # Cognitive/Epistemic frames (Mental actions, not operational tasks)
        "think", "hope", "believe", "guess", "assume", "suppose", "wonder", "feel",
        # Conversational / Discourse markers (Polite background text)
        "mean", "say", "tell", "mention", "hear", "apologize", "thank", "appreciate",
        # Stative / Aspective descriptors (States of being or status)
        "seem", "look", "appear", "stay", "remain", "happen", "exist",
        # Permissive / Volitional shells
        "allow", "permit", "wish", "intend"
    }
    # Verbs that are casual and not necessarily high-value tasks
    CASUAL_VERBS = {
        "read",
        "leave",
        "watch",
        "play",
        "eat",
        "go",
        "view",
    }
    HIGH_VALUE_OBJECT_CUES = {
        "contract", "proposal", "report", "article", "presentation", "doc", "file", "email", "ticket",
        "pr", "code", "policy", "spec", "deck", "invoice", "guideline"
    }

    @staticmethod
    def _normalize_signature_value(value: str | None) -> str:
        value = "" if value is None else str(value)
        value = unicodedata.normalize("NFKC", value)
        value = re.sub(r"\s+", " ", value).strip().casefold()
        return value

    @classmethod
    def _is_casual_action(cls, action: "ExtractedActionPrediction") -> bool:
        """Evaluates whether an action is noise or conversational email pleasantry."""
        if not action:
            return False

        verb = action["verb_primitive"]
        if not verb:
            return True

        # Gate 1: Enforce the Hard Delete Shield
        if verb in cls.HARD_DELETE_VERBS:
            return True

        # Gate 2: Enforce the Allowed Operational Verb Gateway
        if verb not in cls.ALLOWED_ACTION_VERBS:
            # Only drop verbs that are explicitly marked casual; unknown verbs pass through
            if verb not in cls.CASUAL_VERBS:
                return False

        # Gate 3: Casual Context Boundary Checks
        if verb in cls.CASUAL_VERBS or verb not in cls.ALLOWED_ACTION_VERBS:
            # Contextual Override: Save task if high-value corporate cues exist in the sanitized object string
            obj = action["object_primitive"]
            if obj and any(cue in obj for cue in cls.HIGH_VALUE_OBJECT_CUES):
                return False  # Saved by the high-value object cue!

            return True  # Confirmed casual noise

        return False

    @staticmethod
    def _sanitize_object_clause(obj_value: str | None) -> str:
        """Removes trailing dependent clauses and temporal noise from the core noun."""
        if not obj_value:
            return ""

        obj_str = str(obj_value).strip()
        clean_pattern = r"\s+(?:before|after|until|so\s+that|in\s+order\s+to)\b"

        split_parts = re.split(clean_pattern, obj_str, flags=re.IGNORECASE)
        return split_parts[0].strip() if split_parts else obj_str

    @staticmethod
    def _deduplicate_actions(actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        seen_tasks = set()
        deduplicated = []

        for action in actions:
            task_signature = (
                action.get("verb_primitive", ""),
                action.get("object_primitive", ""),
                action.get("source_sentence", ""),
            )
            if task_signature not in seen_tasks:
                seen_tasks.add(task_signature)
                deduplicated.append(action)

        return deduplicated

    @classmethod
    def clean_and_sanitize(cls, actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        """Filters out conversational low-value actions and trims trailing grammatical text."""
        if not actions:
            return []

        processed_actions: List["ExtractedActionPrediction"] = []

        for action in actions:
            # 1. NORMALIZE ONCE: Clean up formatting right at the entryway
            action["verb_primitive"] = cls._normalize_signature_value(action.get("verb_primitive", ""))
            action["object_primitive"] = cls._normalize_signature_value(action.get("object_primitive", ""))
            action["source_sentence"] = cls._normalize_signature_value(action.get("source_sentence", ""))

            # 2. SANITIZE TARGET OBJECTS FIRST: Clean noun clauses BEFORE checking context cues
            if action["object_primitive"]:
                action["object_primitive"] = cls._sanitize_object_clause(action["object_primitive"])

            # 3. FILTER GATEWAY: Evaluate structured text boundaries and allowlists
            if cls._is_casual_action(action):
                continue

            processed_actions.append(action)

        return processed_actions

    @classmethod
    def process(cls, actions: List["ExtractedActionPrediction"]) -> List["ExtractedActionPrediction"]:
        """End-to-end postprocessing pipeline."""
        cleaned_actions = cls.clean_and_sanitize(actions)
        return cls._deduplicate_actions(cleaned_actions)
