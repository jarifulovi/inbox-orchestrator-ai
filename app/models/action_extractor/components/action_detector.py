from typing import List
import spacy


class ActionDetector:
    def __init__(self):
        # Explicit, high-confidence token-level imperative and modal cues
        self.LEXICAL_CUES = {"please", "must", "should", "need", "kindly", "ought"}

        # Idiomatic phrase anchors that introduce background purpose rather than task tasks
        self.PURPOSE_CONJUNCTIONS = {"before", "after", "until", "while", "by", "if", "when"}

        # Clausal dependencies that represent context or descriptions, not active tasks
        self.NON_TASK_DEPS = {"advcl", "acl", "relcl"}

    def is_actionable_verb(self, verb: spacy.tokens.Token, sent: spacy.tokens.Span) -> bool:
        """
        Layer 1: Structural token verification.
        Evaluates a single verb token against its local dependency tree to determine
        if it represents an active assignment.
        """
        # Guard 1: Basic Part-of-Speech Validation
        if verb.pos_ != "VERB":
            return False

        # Guard 2: Exclude structural background, relative, and conditional sub-clauses
        if verb.dep_ in self.NON_TASK_DEPS:
            # Fallback Check: Ensure it isn't an advanced conditional inversion acting as a root
            return False

        # Guard 3: Phrase Fragment Protection (e.g., skip "follow" in "follow-up meeting")
        if verb.i + 1 < len(verb.doc) and verb.doc[verb.i + 1].text == "-":
            return False

        # Guard 4: Targeted Local Negation Validation
        # Only block if the negation token directly modifies THIS verb.
        # This preserves double-negatives like "Don't forget to submit..."
        for child in verb.children:
            if child.dep_ == "neg" and verb.lemma_.lower() not in {"forget", "miss"}:
                return False

        # Guard 5: Ignore conversational or background idioms (e.g., "let me know")
        if verb.lemma_.lower() in {"let", "know"} and any(c.text.lower() == "me" for c in verb.children):
            return False

        # Strategy 1: Syntactic Imperative Command Detection
        # Direct directives do not have explicit nominal subjects and use base-form markers
        has_subject = any(c.dep_ in {"nsubj", "nsubjpass"} for c in verb.children)

        # Check if the verb is preceded closely by a polite imperative marker like "please" or "kindly"
        has_polite_prefix = any(
            t.text.lower() in {"please", "kindly"} and abs(verb.i - t.i) <= 3
            for t in sent
        )

        if (not has_subject and verb.tag_ in {"VB", "VBP"}) or (
                has_polite_prefix and verb.tag_ in {"VB", "VBP", "VBZ"}):
            # Ensure the verb isn't trapped right after a temporal preposition (e.g., "before processing")
            if verb.i > sent.start:
                prev_token = verb.doc[verb.i - 1]
                if prev_token.text.lower() in self.PURPOSE_CONJUNCTIONS:
                    return False
            return True

        # Strategy 2: Modal Request & Obligation Verification
        # Catches structures like: "You must submit", "We need to fix", "You have to update"
        for child in verb.children:
            if child.dep_ == "aux" and child.lemma_.lower() in self.LEXICAL_CUES:
                return True

            # Specific structural catch for "have to [action]"
            if child.dep_ == "aux" and child.lemma_.lower() == "have":
                # Ensure the infinitive particle 'to' matches its siblings
                if any(c.text.lower() == "to" for c in verb.children):
                    return True

        # Traces upstream to see if this verb is driven by an explicit modal matrix head
        # Catches: "needs to update", "should try to review"
        if verb.dep_ in {"xcomp", "ccomp"}:
            head_verb = verb.head
            if head_verb.pos_ == "VERB" and (
                    head_verb.lemma_.lower() in self.LEXICAL_CUES or
                    any(c.dep_ == "aux" and c.lemma_.lower() in self.LEXICAL_CUES for c in head_verb.children)
            ):
                return True

        # Strategy 3: Passive Request Requirements
        # Catches tasks missing direct actors: "The ticket needs to be created", "Must be submitted"
        if verb.tag_ == "VBN" or any(c.dep_ == "nsubjpass" for c in verb.children):
            # Check if it has a passive auxiliary binder ('be', 'been') driven by a modal
            has_passive_aux = any(c.lemma_.lower() == "be" for c in verb.children)
            if has_passive_aux:
                # Upstream head matrix match ("needs to be reviewed")
                if verb.dep_ == "xcomp" and verb.head.lemma_.lower() in self.LEXICAL_CUES:
                    return True
                # Immediate local aux match ("must be reviewed")
                if any(c.dep_ == "aux" and c.lemma_.lower() in self.LEXICAL_CUES for c in verb.children):
                    return True

        # Strategy 4: Non-Recursive Iterative Coordination Inheritance
        # If this verb is a conjunct, trace up to its immediate structural head token.
        # For long lists ("update, test, and deploy"), they inherit actionability from the shared head.
        if verb.dep_ == "conj":
            curr_head = verb.head
            # Loop up to the absolute root of the local coordinate chain safely without a deep recursive stack
            while curr_head.dep_ == "conj" and curr_head.head.pos_ == "VERB" and curr_head != curr_head.head:
                curr_head = curr_head.head

            if curr_head != verb and curr_head.pos_ == "VERB":
                # Call evaluation strictly on the root head token to determine base permission
                return self.is_actionable_verb(curr_head, sent)

        return False