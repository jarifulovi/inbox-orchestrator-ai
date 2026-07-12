import html
import re
import unicodedata
from typing import List, Dict, Any

try:
    import contractions as contractions_lib
except ImportError:
    contractions_lib = None


class TextPreprocessor:
    STRUCTURAL_REMOVALS = (
        r"(?im)^\s*(from|sent|to|cc|bcc|subject|date)\s*:\s*.*$",
        r"(?im)^\s*on .+wrote:\s*$",
        r"(?im)^\s*[-_ ]*forwarded message[-_ ]*$",
        r"(?im)^\s*[-*_~=]{3,}\s*$",
    )

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
        cleaned = cls._structural_clean(text)
        cleaned = cls._expand_contractions(cleaned)
        cleaned = cls._normalize_syntax(cleaned)
        return cleaned


class FactPostprocessor:
    ALLOWED_ACTION_VERBS = {
        "verify", "review", "submit", "update", "approve", "confirm",
        "check", "send", "sign", "complete", "schedule", "track"
    }
    HARD_DELETE_VERBS = {
        "let", "shall",
        "think", "hope", "believe", "guess", "assume", "suppose", "wonder", "feel",
        "mean", "say", "tell", "mention", "hear", "apologize", "thank", "appreciate",
        "seem", "look", "appear", "stay", "remain", "happen", "exist",
        "allow", "permit", "wish", "intend"
    }
    CASUAL_VERBS = {
        "read", "leave", "watch", "play", "eat", "go", "view",
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
    def _is_casual_action(cls, action_verb: str, object_prim: str | None) -> bool:
        if not action_verb:
            return True

        if action_verb in cls.HARD_DELETE_VERBS:
            return True

        # If it is a known casual verb, we only allow it if it acts on a high-value object
        if action_verb in cls.CASUAL_VERBS:
            if object_prim and any(cue in object_prim for cue in cls.HIGH_VALUE_OBJECT_CUES):
                return False
            return True

        return False

    @staticmethod
    def _sanitize_object_clause(obj_value: str | None) -> str:
        if not obj_value:
            return ""

        obj_str = str(obj_value).strip()
        clean_pattern = r"\s+(?:before|after|until|so\s+that|in\s+order\s+to)\b"

        split_parts = re.split(clean_pattern, obj_str, flags=re.IGNORECASE)
        return split_parts[0].strip() if split_parts else obj_str

    @classmethod
    def process(cls, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Deduplicates facts and sanitizes task/commitment payloads.
        """
        if not facts:
            return []

        processed_facts = []
        seen_signatures = set()

        for fact in facts:
            fact_type = fact.get("fact_type", "fact")
            payload = fact.get("payload", {})
            source_sentence = cls._normalize_signature_value(fact.get("source_sentence", ""))

            # Sanitize and check tasks and commitments
            if fact_type in {"task", "commitment"}:
                action_verb = cls._normalize_signature_value(payload.get("action", ""))
                object_prim = cls._normalize_signature_value(payload.get("object", ""))
                
                # Sanitize target object
                if object_prim:
                    object_prim = cls._sanitize_object_clause(object_prim)
                
                # Check for casual actions/noise
                if cls._is_casual_action(action_verb, object_prim):
                    # Demote to a generic fact or drop if completely noisy
                    if action_verb in cls.HARD_DELETE_VERBS:
                        continue  # Skip hard deletes entirely
                    fact_type = "fact"
                    payload["action"] = action_verb
                    payload["object"] = object_prim
                else:
                    payload["action"] = action_verb
                    payload["object"] = object_prim

            fact["fact_type"] = fact_type
            fact["source_sentence"] = source_sentence
            
            # Normalize other strings
            fact["model_version"] = str(fact.get("model_version", ""))

            # Deduplication key
            signature = (
                fact_type,
                payload.get("action", ""),
                payload.get("object", ""),
                source_sentence
            )

            if signature not in seen_signatures:
                seen_signatures.add(signature)
                processed_facts.append(fact)

        return processed_facts
