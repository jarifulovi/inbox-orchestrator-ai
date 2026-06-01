from typing import List
import spacy


class ActionDetector:
    def __init__(self):
        # Operational verbs that signify real-world business tasks
        self.ACTION_VERBS = {
            "print", "submit", "review", "sign", "send", "call", "launch",
            "update", "verify", "check", "email", "forward", "prepare",
            "compile", "fix", "schedule", "meeting", "write", "approve"
        }

        # Keywords that signal a direct request, requirement, or necessity
        self.ACTIONABLE_CUES = {
            "please", "need", "must", "should", "have to", "require", "task", "action"
        }

        # Negative cues to drop tasks
        self.NEGATION_WORDS = {"not", "don't", "dont", "never", "stop", "cancel"}


    def is_actionable_sentence(self, sent: spacy.tokens.Span) -> bool:
        """
        Layer 1: Analyzes a sentence to determine if it expresses an inherent task.
        Returns True if it passes basic structural and vocabulary filters.
        """
        sentence_text = sent.text.lower()

        # If the sentence contains clear negation, it's a "don't do" directive -> skip.
        if any(neg in sentence_text for neg in self.NEGATION_WORDS):
            return False

        # Also check spaCy's internal dependency tags for negation
        if any(t.dep_ == "neg" for t in sent):
            return False

        # Rule 1: Catch sentences containing explicit urgent request cues
        has_cue = any(cue in sentence_text for cue in self.ACTIONABLE_CUES)

        # Rule 2: Verify if the sentence contains an explicit operational action verb
        # We look at the root token lemmas to capture all morphological tenses cleanly
        has_action_verb = any(t.lemma_.lower() in self.ACTION_VERBS for t in sent if t.pos_ in ["VERB", "NOUN"])

        # Rule 3: Catch direct imperative verbs (e.g., "Print the document.")
        # Imperatives typically start sentences directly or follow punctuation without explicit subject pronouns
        has_imperative = False
        first_token = next((t for t in sent if t.pos_ != "PUNCT"), None)
        if first_token and first_token.pos_ == "VERB" and first_token.lemma_.lower() in self.ACTION_VERBS:
            has_imperative = True

        # Decision Matrix: It's actionable if it has a core action verb AND (a request cue OR direct imperative structure)
        if has_action_verb and (has_cue or has_imperative):
            return True

        return False

    def filter_actionable_sentences(self, doc: spacy.tokens.Doc) -> List[spacy.tokens.Span]:
        """
        Helper method to quickly isolate candidate task sentences from a full document body.
        """
        return [sent for sent in doc.sents if self.is_actionable_sentence(sent)]