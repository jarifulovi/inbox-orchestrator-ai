import re
from typing import List, Dict, Any

class FactTypeChecker:
    # Cues for standard greetings, conversational sign-offs, and disclaimers to treat as noise
    BOILERPLATE_CUES = {
        "thanks", "thank you", "best regards", "kind regards", "sincerely",
        "regards", "best", "dear", "hi", "hello", "hey", "good morning",
        "good afternoon", "good evening", "cheers", "yours truly", "respectfully",
        "sent from my iphone", "sent from my mail", "all the best", "warm regards"
    }

    # Questions that are conversational check-ins rather than informational requests
    RHETORICAL_QUESTION_PHRASES = {
        "how are you", "hope you are well", "hope all is well", "how is it going",
        "hope you are doing well", "hope this finds you well", "how have you been"
    }

    @classmethod
    def validate_fact_types(cls, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validates and refines parsed facts, aggressively dropping conversational noise,
        boilerplate text, greetings, and rhetorical check-in questions.
        """
        valid_facts = []

        for fact in facts:
            fact_type = fact.get("fact_type")
            payload = fact.get("payload", {})
            source_sentence = fact.get("source_sentence", "").strip()
            source_sentence_lower = source_sentence.lower()

            # 1. Broad Noise Filter: Check if the sentence is pure boilerplate/sign-off
            # Clean punctuation from start/end to catch e.g., "Thanks," or "Best regards!"
            cleaned_sentence = re.sub(r"^[^\w]+|[^\w]+$", "", source_sentence_lower)
            if cleaned_sentence in cls.BOILERPLATE_CUES:
                continue

            # Skip sentences that are just signature fragments or empty links
            if not cleaned_sentence or cleaned_sentence in {"[link]", "link", "opt out"}:
                continue

            # Skip generic conversational filler phrases
            if cleaned_sentence in {"thanks and regards", "thanks & regards", "best wishes"}:
                continue

            # 2. Fact-Type Specific Verification
            if fact_type == "question":
                # Filter out rhetorical / check-in questions
                if any(phrase in source_sentence_lower for phrase in cls.RHETORICAL_QUESTION_PHRASES):
                    continue

                # Ensure it actually has interrogative properties (ends in ? or starts with auxiliary / WH-word)
                has_q_mark = "?" in source_sentence_lower
                starts_with_interrogative = any(
                    source_sentence_lower.startswith(w) for w in {
                        "what", "when", "where", "who", "whom", "why", "how",
                        "can", "could", "would", "should", "will", "is", "are",
                        "do", "does", "did", "may", "might", "shall", "has", "have"
                    }
                )
                if not (has_q_mark or starts_with_interrogative):
                    continue

            elif fact_type == "decision":
                # Ensure a decision isn't built around trivial or conversational filler verbs
                action = payload.get("action")
                if action and action in {"say", "tell", "thank", "apologize", "greet", "hope"}:
                    continue

            elif fact_type == "fact":
                # Check for substring matches of standard signature disclaimers/greetings
                has_boilerplate_word = any(cue in source_sentence_lower for cue in {
                    "thanks", "thank you", "regards", "sincerely", "cheers", "best wishes",
                    "sent from", "iphone", "android", "outlook", "best regards", "kind regards",
                    "dear", "hi", "hello"
                })
                # If it has a boilerplate cue and is short, skip it
                if has_boilerplate_word and len(source_sentence_lower.split()) <= 8:
                    continue

                # Ensure generic facts are not just extremely short noise fragments (e.g. <= 3 words)
                words = [w for w in source_sentence_lower.split() if w.strip()]
                # Skip if it is too short and has no high-value noun chunks/entities
                if len(words) <= 3:
                    continue

            # If it passes all noise checks, keep it
            valid_facts.append(fact)

        return valid_facts
