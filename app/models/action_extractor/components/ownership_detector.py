import spacy


class OwnershipDetector:
    def __init__(self):
        # Pronouns that indicate someone else is doing the action
        self.THIRD_PERSON_PRONOUNS = {"he", "she", "they", "it"}

    def is_assigned_to_me(self, sent: spacy.tokens.Span) -> bool:
        """
        Layer 2: Checks if the task is directed at the reader ('me').
        Returns True if the text targets the reader, False if assigned to others.
        """
        # Find the main root verb of the sentence
        root_verb = next((t for t in sent if t.dep_ == "ROOT"), None)

        # Track subjects across the sentence
        has_third_person_subject = False
        has_first_or_second_person_subject = False

        for token in sent:
            # Look for subjects (nsubj = nominal subject)
            if token.dep_ in {"nsubj", "nsubjpass"}:
                token_text = token.text.lower()

                # Check for other people explicitly named (Proper Nouns like 'John')
                if token.pos_ == "PROPN":
                    has_third_person_subject = True

                # Check for third-person pronouns ('he', 'she', 'they')
                elif token_text in self.THIRD_PERSON_PRONOUNS:
                    has_third_person_subject = True

                # Check for first/second person ('i', 'we', 'you')
                elif token_text in {"i", "we", "you"}:
                    has_first_or_second_person_subject = True

        # Rule 1: Explicitly assigned to someone else -> Reject immediately
        if has_third_person_subject and not has_first_or_second_person_subject:
            return False

        # Rule 2: Check for direct Imperatives / Direct Commands
        # If a sentence starts with an action or request cue and has no explicit subject,
        # it is an imperative targeting 'You' (the reader).
        first_token = next((t for t in sent if t.pos_ != "PUNCT"), None)
        if first_token and (first_token.text.lower() == "please" or first_token.pos_ == "VERB"):
            return True

        # Rule 3: Check for passive obligations (e.g., "must be submitted")
        # In business emails, missing subjects with modal verbs imply reader/team obligation.
        has_modal_obligation = any(t.lemma_.lower() in {"must", "should", "need"} for t in sent)
        is_passive = any(t.dep_ == "nsubjpass" or t.lemma_.lower() == "be" for t in sent)
        if has_modal_obligation and is_passive:
            return True

        # Rule 4: Explicit first/second person actor ("We need to...", "I will...")
        if has_first_or_second_person_subject:
            return True

        # Fallback default: If completely ambiguous, treat it as a candidate task
        return True