from typing import List, Dict, Any

class FactTypeChecker:
    # Questions that are conversational check-ins rather than informational requests
    RHETORICAL_QUESTION_PHRASES = {
        "how are you", "hope you are well", "hope all is well", "how is it going",
        "hope you are doing well", "hope this finds you well", "how have you been"
    }

    @classmethod
    def validate_fact_types(cls, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validates and refines parsed facts, dropping rhetorical questions and invalid assignments.
        """
        valid_facts = []

        for fact in facts:
            fact_type = fact.get("fact_type")
            payload = fact.get("payload", {})
            source_sentence = fact.get("source_sentence", "").strip()
            source_sentence_lower = source_sentence.lower()

            # Skip empty or link-only facts
            if not source_sentence_lower or source_sentence_lower in {"[link]", "link", "opt out"}:
                continue

            # Fact-Type Specific Verification
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
                # Ensure generic facts are not just extremely short noise fragments (e.g. <= 3 words)
                words = [w for w in source_sentence_lower.split() if w.strip()]
                if len(words) <= 3:
                    continue

            # If it passes all noise checks, keep it
            valid_facts.append(fact)

        return valid_facts
