from spacy.tokens import Token, Span

class ActionDetector:
    def __init__(self):
        self.LEXICAL_CUES = {"please", "must", "should", "need", "kindly", "ought"}
        self.PURPOSE_CONJUNCTIONS = {"before", "after", "until", "while", "by", "if", "when"}
        self.NON_TASK_DEPS = {"advcl", "acl", "relcl"}

    def is_actionable_verb(self, verb: Token, sent: Span) -> bool:
        if verb.pos_ != "VERB":
            return False

        # Guard: Explicitly skip ambiguous requests with indefinite owners
        if any(c.text.lower() in {"someone", "somebody", "anybody", "anyone"} for c in verb.children if c.dep_ == "nsubj"):
            return False

        # Ignore embedded conditional/modifier clauses unless explicitly commanded
        if verb.dep_ in self.NON_TASK_DEPS and verb.head.lemma_.lower() not in {"remember", "make"}:
            return False

        if verb.i + 1 < len(verb.doc) and verb.doc[verb.i + 1].text == "-":
            return False

        for child in verb.children:
            if child.dep_ == "neg" and verb.lemma_.lower() not in {"forget", "miss"}:
                return False

        if verb.lemma_.lower() in {"let"} and any(c.text.lower() == "me" for c in verb.children):
            if verb.dep_ != "conj":
                return False

        has_subject = any(c.dep_ in {"nsubj", "nsubjpass"} for c in verb.children)
        has_polite_prefix = any(
            t.text.lower() in {"please", "kindly", "remember", "make"} and abs(verb.i - t.i) <= 4
            for t in sent
        )

        # Catch raw imperatives and politeness-framed actions
        if (not has_subject and verb.tag_ in {"VB", "VBP"}) or has_polite_prefix:
            if verb.i > sent.start:
                prev_token = verb.doc[verb.i - 1]
                if prev_token.text.lower() in self.PURPOSE_CONJUNCTIONS:
                    return False
            return True

        # Catch items linked via modal auxiliaries
        for child in verb.children:
            if child.dep_ == "aux" and child.lemma_.lower() in self.LEXICAL_CUES:
                return True
            if child.dep_ == "aux" and child.lemma_.lower() == "have":
                if any(c.text.lower() == "to" for c in verb.children):
                    return True

        # Catch open clausal structures driven by matrix prompts ("Remember to renew")
        if verb.dep_ in {"xcomp", "ccomp"}:
            head_verb = verb.head
            if head_verb.pos_ == "VERB" and (
                    head_verb.lemma_.lower() in self.LEXICAL_CUES or
                    head_verb.lemma_.lower() in {"remember", "make", "sure"} or
                    any(c.dep_ == "aux" and c.lemma_.lower() in self.LEXICAL_CUES for c in head_verb.children)
            ):
                return True

        # Handle coordinate family structures
        if verb.dep_ == "conj":
            # If this verb has its own explicit subject it governs its own clause
            # (e.g., "so accounting can process it") — don't inherit from parent
            if any(c.dep_ in {"nsubj", "nsubjpass"} for c in verb.children):
                return False
            curr_head = verb.head
            while curr_head.dep_ == "conj" and curr_head.head.pos_ == "VERB" and curr_head != curr_head.head:
                curr_head = curr_head.head
            if curr_head != verb and curr_head.pos_ == "VERB":
                return self.is_actionable_verb(curr_head, sent)

        return False