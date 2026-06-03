import spacy
from typing import Set, Dict
from spacy.tokens import Token


class OwnershipDetector:
    def __init__(self):
        # 1. Closed-Class Grammatical Pronouns
        self.THIRD_PERSON_PRONOUNS: Set[str] = {"he", "she", "they", "it"}
        self.LOCAL_TEAM_PRONOUNS: Set[str] = {"i", "we", "you"}

        # 2. Structural/Semantic Functional Verb Classes
        # Verbs that shift future operational liability to an external entity
        self.DELEGATION_VERBS: Set[str] = {"assign", "delegate", "appoint", "nominate"}

        # Verbs that command the reader to physically move/route a data asset
        self.ASSET_ROUTING_VERBS: Set[str] = {"forward", "route", "pass", "send", "transfer", "ship"}

    def is_verb_assigned_to_me(self, verb: Token) -> bool:
        """
        Main orchestration endpoint. Evaluates if the action described by the
        verb token belongs to the reader/local team or an external entity.
        """
        if verb.pos_ != "VERB":
            return False

        # Stage 1: Resolve grammar dependencies up to the controlling verb
        governing_verb = self._resolve_governing_root(verb)

        # Stage 2: Extract explicit linguistic roles present in the clause
        clause_roles = self._extract_clause_roles(governing_verb)

        # Stage 3: Evaluate extracted roles against business routing rules
        return self._evaluate_routing_matrix(governing_verb, clause_roles)

    def _resolve_governing_root(self, verb: Token) -> Token:
        """Iteratively traces conjunction chains to find the true structural root."""
        curr = verb
        while curr.dep_ == "conj" and curr.head.pos_ == "VERB" and curr != curr.head:
            curr = curr.head
        return curr

    def _extract_clause_roles(self, verb: Token) -> Dict[str, bool]:
        """Scans the verb's immediate children and subtrees to isolate actor roles."""
        roles = {
            "has_local_subject": False,
            "has_external_subject": False,
            "has_external_destination": False
        }

        for child in verb.children:
            # A. Analyze Direct/Passive Clause Subjects
            if child.dep_ in {"nsubj", "nsubjpass"}:
                self._classify_subject_actor(child, roles)

            # B. Analyze Passive Agents (e.g., "processed by accounting")
            elif child.dep_ == "agent":
                self._classify_passive_agent(child, roles)

            # C. Analyze Indirect Objects & Destination Prepositions (e.g., "to Sarah")
            elif child.dep_ in {"dative", "prep"} or child.text.lower() == "to":
                self._classify_destination_recipient(child, roles)

        return roles

    def _classify_subject_actor(self, token: Token, roles: Dict[str, bool]) -> None:
        """Determines if a clausal subject points inside or outside the local team."""
        text_lower = token.text.lower()

        if text_lower in self.LOCAL_TEAM_PRONOUNS:
            roles["has_local_subject"] = True
        elif text_lower in self.THIRD_PERSON_PRONOUNS:
            roles["has_external_subject"] = True
        elif token.pos_ in {"NOUN", "PROPN"}:
            # Broad/Generic architectural fix: Any named entity or explicit common noun
            # (e.g., 'client', 'accounting', 'manager') represents a third-party actor.
            roles["has_external_subject"] = True

    def _classify_passive_agent(self, agent_token: Token, roles: Dict[str, bool]) -> None:
        """Inspects the subtree of a passive agent bypass to detect third-party actors."""
        for node in agent_token.subtree:
            node_lower = node.text.lower()
            if node_lower in self.LOCAL_TEAM_PRONOUNS:
                roles["has_local_subject"] = True
            elif node_lower in self.THIRD_PERSON_PRONOUNS or node.pos_ in {"NOUN", "PROPN"}:
                roles["has_external_subject"] = True

    def _classify_destination_recipient(self, prep_token: Token, roles: Dict[str, bool]) -> None:
        """Detects if an action redirects something to an external third-party target."""
        for node in prep_token.subtree:
            node_lower = node.text.lower()
            # If the recipient is explicitly an external noun and not a local team pronoun
            if (node.pos_ in {"NOUN", "PROPN"} or node_lower in self.THIRD_PERSON_PRONOUNS) and (
                    node_lower not in self.LOCAL_TEAM_PRONOUNS):
                roles["has_external_destination"] = True

    def _evaluate_routing_matrix(self, verb: Token, roles: Dict[str, bool]) -> bool:
        """Applies generalized business logic rules to the extracted structural roles."""
        verb_lemma = verb.lemma_.lower()

        # Rule 1: Asset Routing Override (MOVE TO THE VERY TOP)
        # If the verb commands the reader to route an asset ("Forward this email to X"),
        # the reader still perfectly owns the immediate task of performing the transfer.
        if verb_lemma in self.ASSET_ROUTING_VERBS:
            return True

        # Rule 2: Structural Delegation Check
        # If the verb explicitly shifts future operational liability away ("Assign this to X"),
        # the reader STILL owns the immediate command to execute the assignment.
        # Only reject if an external subject is doing the assigning ("John will assign...").
        if verb_lemma in self.DELEGATION_VERBS and roles["has_external_destination"]:
            if roles["has_external_subject"] and not roles["has_local_subject"]:
                return False
            return True  # Reader owns the act of assigning!

        # Rule 3: Explicit Third-Party Execution Check
        # If the clause explicitly isolates an external subject as the executor of this specific
        # verb (e.g., "so accounting can process it"), and no local team pronoun overrides it.
        if roles["has_external_subject"] and not roles["has_local_subject"]:
            return False

        # Fallback Default: If no explicit third-party execution is proven,
        # treat it as a directive targeted directly at the local team.
        return True