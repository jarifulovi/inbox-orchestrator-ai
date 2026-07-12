from typing import Set, Dict
from spacy.tokens import Token

class OwnershipDetector:
    def __init__(self):
        # 1. Closed-Class Grammatical Pronouns
        self.THIRD_PERSON_PRONOUNS: Set[str] = {"he", "she", "they", "it"}
        self.LOCAL_TEAM_PRONOUNS: Set[str] = {"i", "we", "you"}

    def determine_subject_actor(self, verb: Token) -> str:
        """
        Determines the grammatical actor of the verb (e.g., "recipient", "sender", "third-party").
        """
        governing_verb = self._resolve_governing_root(verb)
        clause_roles = self._extract_clause_roles(governing_verb)

        # Check subject types to assign actor label
        if clause_roles["has_recipient_subject"]:
            return "recipient"
        elif clause_roles["has_sender_subject"]:
            return "sender"
        elif clause_roles["has_external_subject"]:
            return "third-party"
        
        # If no subject is present (e.g. "Please print the report"), it's an imperative to the recipient.
        return "recipient"

    def _resolve_governing_root(self, verb: Token) -> Token:
        """Iteratively traces conjunction chains to find the true structural root.
        Stops early when the current verb has its own explicit subject."""
        curr = verb
        while curr.dep_ == "conj" and curr.head.pos_ == "VERB" and curr != curr.head:
            if any(c.dep_ in {"nsubj", "nsubjpass"} for c in curr.children):
                break
            curr = curr.head
        return curr

    def _extract_clause_roles(self, verb: Token) -> Dict[str, bool]:
        """Scans the verb's immediate children and subtrees to isolate actor roles."""
        roles = {
            "has_local_subject": False,
            "has_sender_subject": False,
            "has_recipient_subject": False,
            "has_external_subject": False
        }

        for child in verb.children:
            if child.dep_ in {"nsubj", "nsubjpass"}:
                self._classify_subject_actor(child, roles)
            elif child.dep_ == "agent":
                self._classify_passive_agent(child, roles)

        return roles

    def _classify_subject_actor(self, token: Token, roles: Dict[str, bool]) -> None:
        """Determines if a clausal subject points inside or outside the local team."""
        text_lower = token.text.lower()

        if text_lower in {"i", "we"}:
            roles["has_local_subject"] = True
            roles["has_sender_subject"] = True
        elif text_lower == "you":
            roles["has_local_subject"] = True
            roles["has_recipient_subject"] = True
        elif text_lower in self.THIRD_PERSON_PRONOUNS:
            roles["has_external_subject"] = True
        elif token.pos_ in {"NOUN", "PROPN"}:
            roles["has_external_subject"] = True

    def _classify_passive_agent(self, agent_token: Token, roles: Dict[str, bool]) -> None:
        """Inspects the subtree of a passive agent bypass to detect third-party actors."""
        for node in agent_token.subtree:
            node_lower = node.text.lower()
            if node_lower in {"i", "we"}:
                roles["has_local_subject"] = True
                roles["has_sender_subject"] = True
            elif node_lower == "you":
                roles["has_local_subject"] = True
                roles["has_recipient_subject"] = True
            elif node_lower in self.THIRD_PERSON_PRONOUNS or node.pos_ in {"NOUN", "PROPN"}:
                roles["has_external_subject"] = True
