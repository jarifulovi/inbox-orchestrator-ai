import spacy


class OwnershipDetector:
    def __init__(self):
        # Pronouns that indicate someone else is explicitly doing the action
        self.THIRD_PERSON_PRONOUNS = {"he", "she", "they", "it"}

        # Verbs that explicitly route ownership away via indirect objects or destinations
        self.ASSIGNMENT_VERBS = {"assign", "delegate", "give", "route", "forward", "pass"}

    def is_verb_assigned_to_me(self, verb: spacy.tokens.Token) -> bool:
        """
        Layer 2: Token-Level Clause Assignment Analyzer.
        Determines ownership specifically for the clause governed by this verb.
        Returns True if assigned to the reader/team, False if assigned away to others.
        """
        if verb.pos_ != "VERB":
            return False

        # --- STEP 1: RESOLVE COORDINATE INHERITANCE ITERATIVELY (NO RECURSION) ---
        # If this verb is part of a serial verb chain ("update, test, and deploy"),
        # crawl up to the primary governing root verb to analyze base ownership.
        curr_verb = verb
        while curr_verb.dep_ == "conj" and curr_verb.head.pos_ == "VERB" and curr_verb != curr_verb.head:
            curr_verb = curr_verb.head

        # --- STEP 2: SCAN CLAUSE FOR THIRD-PARTY ACTORS ---
        has_third_person_subject = False
        has_first_or_second_person_subject = False
        has_third_party_destination = False

        for child in curr_verb.children:
            # A. Standard Clause Subjects
            if child.dep_ in {"nsubj", "nsubjpass"}:
                child_text = child.text.lower()

                if child.pos_ == "PROPN":
                    has_third_person_subject = True
                elif child_text in self.THIRD_PERSON_PRONOUNS:
                    has_third_person_subject = True
                elif child_text in {"i", "we", "you"}:
                    has_first_or_second_person_subject = True

            # B. Passive Agent Tracking: Catching "must be submitted by John"
            elif child.dep_ == "agent":
                # Scan the agent preposition's subtree for proper nouns or third person markers
                for agent_child in child.subtree:
                    if agent_child.pos_ == "PROPN" or agent_child.text.lower() in self.THIRD_PERSON_PRONOUNS:
                        has_third_person_subject = True

            # C. Assignment Tracking: Catching "Assign the task to Sarah"
            elif child.dep_ in {"dative", "prep"} or child.text.lower() == "to":
                # If the action verb is an explicit assignment command routing away from the reader
                if curr_verb.lemma_.lower() in self.ASSIGNMENT_VERBS:
                    for prep_child in child.subtree:
                        if prep_child.pos_ == "PROPN" or prep_child.text.lower() in self.THIRD_PERSON_PRONOUNS:
                            has_third_party_destination = True

        # --- STEP 3: APPLY ASSIGNMENT DECISION RULES ---

        # Rule 1: Explicitly reassigned destination (e.g., "Assign task to Sarah") -> Reject immediately
        if has_third_party_destination:
            return False

        # Rule 2: Explicitly assigned to someone else via subject/agent clause -> Reject immediately
        if has_third_person_subject and not has_first_or_second_person_subject:
            return False

        # Fallback Default: If no explicit third-party assignment is found,
        # treat the directive as a task directed at the reader/team.
        return True