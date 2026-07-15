from typing import Set
from spacy.tokens import Span

class SentenceValidator:
    BOILERPLATE_CUES = {
        "thanks", "thank you", "best regards", "kind regards", "sincerely",
        "regards", "best", "dear", "hi", "hello", "hey", "good morning",
        "good afternoon", "good evening", "cheers", "yours truly", "respectfully",
        "sent from my iphone", "sent from my mail", "all the best", "warm regards",
        "best wishes", "warmest regards", "thanks & regards", "thanks and regards",
        "many thanks", "with thanks", "regards,"
    }

    @classmethod
    def is_valid_fact_sent(cls, sent: Span) -> bool:
        """
        Validates whether a sentence Span should be processed for fact extraction.
        Aggressively filters greetings, sign-offs, boilerplates, and extremely short noise.
        """
        # Extract alphanumeric words
        words = [t.text.strip().lower() for t in sent if t.text.strip() and not t.is_punct]
        num_words = len(words)
        
        if num_words == 0:
            return False

        clean_sent = " ".join(words)

        # 1. Direct Boilerplate / Sign-off matches
        if clean_sent in cls.BOILERPLATE_CUES:
            return False

        # Check if clean_sent starts with a common greeting/sign-off followed by a name or space
        # e.g., "hi steve", "dear team", "regards john"
        for cue in cls.BOILERPLATE_CUES:
            if clean_sent.startswith(cue + " ") or clean_sent == cue:
                return False

        # 2. Check for signature patterns or automated confidentiality notices
        if clean_sent.startswith("disclaimer") or clean_sent.startswith("confidentiality notice"):
            return False

        # 3. Word count check (single/double word count constraints)
        if num_words <= 2:
            # If the sentence has <= 2 words, it must contain a verb to be considered actionable.
            # e.g., "Call me" (verb), "Email back" (verb) vs "Best wishes" (no verb)
            has_verb = any(t.pos_ == "VERB" for t in sent)
            if not has_verb:
                return False
            
            # Even if it has a verb, if any of the words are common boilerplate cues, skip it.
            if any(w in cls.BOILERPLATE_CUES for w in words):
                return False

        return True
