from datetime import datetime
from typing import List, Any
import spacy

from app.schemas.extracted_actions import ExtractedActionPrediction
from app.models.action_extractor.components.action_detector import ActionDetector
from app.models.action_extractor.components.ownership_detector import OwnershipDetector


class ActionParser:
    TARGET_DEPS = {"dobj", "obj", "pobj", "attr", "nsubjpass"}
    MODAL_VERBS = {"need", "want", "try", "go", "have", "must", "should", "remember"}
    PURPOSE_ANCHORS = {"to", "so", "such", "thereby", "thus", "meaning"}
    STRUCTURAL_TRANSITIONS = {"and", "but", "then", "or", "yet", "so"}

    def __init__(self):
        pass

    @classmethod
    def parse_action_phrases(cls, doc) -> List[ExtractedActionPrediction]:
        extracted_actions: List[ExtractedActionPrediction] = []

        detector = ActionDetector()
        ownership = OwnershipDetector()

        for sent in doc.sents:
            deadline = None
            raw_entities_list = [{"text": ent.text, "label": ent.label_} for ent in sent.ents]
            verbs = cls._heal_misclassified_serial_verbs(sent)

            for verb in verbs:
                # Filter out verbal adjectives (e.g., "completed projects")
                if verb.dep_ in {"amod", "nmod"}:
                    continue

                if not detector.is_actionable_verb(verb, sent):
                    continue

                if not ownership.is_verb_assigned_to_me(verb):
                    continue

                if cls._is_trapped_in_purpose_clause(sent, verb, verbs):
                    continue

                verb_lemma = verb.lemma_.lower()

                if verb_lemma in {"let", "know", "remember"} and verb.dep_ != "conj":
                    continue

                if verb_lemma == "regard" or verb.text.lower() == "regarding":
                    continue

                if verb_lemma in cls.MODAL_VERBS and verb.dep_ != "conj":
                    has_xcomp_relation = any(c.dep_ in {"xcomp", "ccomp"} for c in verb.subtree if c != verb)
                    if has_xcomp_relation or verb.dep_ == "aux":
                        continue

                direct_objects = [c for c in verb.children if c.dep_ in cls.TARGET_DEPS]

                if not direct_objects:
                    passive_targets = [t for t in verb.subtree if t.dep_ == "nsubjpass"]
                    if passive_targets:
                        direct_objects = passive_targets

                # Family Coordination Sibling Syncing (Ensures serial verbs inherit targets correctly)
                if not direct_objects:
                    root_verb = verb
                    while root_verb.dep_ == "conj" and root_verb.head.pos_ == "VERB" and root_verb != root_verb.head:
                        root_verb = root_verb.head

                    # FIXED LINE: Grabs all sequential chain verbs from the tree branch
                    coordinate_family = [t for t in root_verb.subtree if t.pos_ == "VERB"]
                    if root_verb not in coordinate_family:
                        coordinate_family.append(root_verb)

                    for sibling in coordinate_family:
                        sibling_objects = [c for c in sibling.children if c.dep_ in cls.TARGET_DEPS]
                        if sibling_objects:
                            direct_objects = sibling_objects
                            break

                all_objects = []
                for dobj in direct_objects:
                    if dobj.pos_ == "PRON" and dobj.text.lower() in {"this", "it", "them", "both"} and len(direct_objects) > 1:
                        continue
                    all_objects.append(dobj)
                    conjuncts = [c for c in dobj.subtree if c.dep_ == "conj" and c.pos_ in ["NOUN", "PROPN", "PRON"]]
                    all_objects.extend(conjuncts)

                if all_objects:
                    for obj_token in all_objects:
                        base_obj_text = obj_token.text.lower()

                        # --- HYPHENATED DESCRIPTOR COMPILER ---
                        # Sort left elements by token index positioning to build the prefix string in sequence
                        left_tokens = sorted([t for t in obj_token.lefts if t.dep_ in {"compound", "amod"}], key=lambda x: x.i)

                        left_compounds = []
                        for lt in left_tokens:
                            # Safely check look-ahead stream tokens for punctuation splits (e.g. "follow", "-", "up")
                            if lt.i + 1 < len(doc) and doc[lt.i + 1].text == "-":
                                hyphenated_term = f"{lt.text}-{doc[lt.i + 2].text}" if lt.i + 2 < len(doc) else lt.text
                                left_compounds.append(hyphenated_term.lower())
                            elif lt.text == "-" or (lt.i - 1 >= 0 and doc[lt.i - 1].text == "-"):
                                continue  # Skip fragments absorbed during look-ahead reconstruction
                            else:
                                left_compounds.append(lt.text.lower())

                        if left_compounds:
                            full_obj_text = f"{' '.join(left_compounds)} {base_obj_text}".strip()
                        else:
                            full_obj_text = base_obj_text

                        # Anaphora pronoun contextual resolution fallback logic
                        if full_obj_text in {"it", "them", "this", "that", "both"} and len(extracted_actions) > 0:
                            for prev_act in reversed(extracted_actions):
                                if prev_act.object_primitive and prev_act.object_primitive not in {"it", "them", "this", "that", "both"}:
                                    full_obj_text = prev_act.object_primitive
                                    break

                        action_prediction = ExtractedActionPrediction(
                            verb_primitive=verb.lemma_.lower(),
                            object_primitive=full_obj_text,
                            source_sentence=sent.text.strip(),
                            parsed_deadline=deadline,
                            raw_entities=raw_entities_list
                        )
                        extracted_actions.append(action_prediction)
                else:
                    action_prediction = ExtractedActionPrediction(
                        verb_primitive=verb.lemma_.lower(),
                        object_primitive=None,
                        source_sentence=sent.text.strip(),
                        parsed_deadline=deadline,
                        raw_entities=raw_entities_list
                    )
                    extracted_actions.append(action_prediction)

        return extracted_actions

    @classmethod
    def _is_trapped_in_purpose_clause(cls, sent, verb, verbs_list) -> bool:
        if verb.dep_ not in {"advcl", "xcomp"}:
            return False

        prev_verb_sent_idx = 0
        try:
            current_idx = verbs_list.index(verb)
            if current_idx > 0:
                prev_verb = verbs_list[current_idx - 1]
                prev_verb_sent_idx = prev_verb.i - sent.start + 1
        except ValueError:
            pass

        # Work with actual token objects instead of raw lower strings to make multi-token phrase sweeps robust
        local_tokens = sent[prev_verb_sent_idx: verb.i - sent.start]
        if not local_tokens:
            return False

        start_idx = 0
        for i, token in enumerate(local_tokens):
            t_text = token.text.lower()

            # Catch structural transitions ("and", "but", etc.)
            if t_text in cls.STRUCTURAL_TRANSITIONS:
                # Upgraded tracking logic: Verify if 'so' is followed immediately by 'that'
                if t_text == "so" and i + 1 < len(local_tokens) and local_tokens[i + 1].text.lower() == "that":
                    start_idx = i + 1
                else:
                    start_idx = i

        # Slice down the active analysis window
        window_tokens = local_tokens[start_idx:]

        for i, token in enumerate(window_tokens):
            t_text = token.text.lower()
            if t_text in cls.PURPOSE_ANCHORS:
                return True
            # Explicitly intercept multi-token phrase "so that" matching inside window boundaries
            if t_text == "so" and i + 1 < len(window_tokens) and window_tokens[i + 1].text.lower() == "that":
                return True

        return False


    @classmethod
    def _heal_misclassified_serial_verbs(cls, sent) -> List[spacy.tokens.Token]:
        """
        Heals serial action elements (e.g., 'test' in 'update, test, and deploy')
        that spaCy occasionally misclassifies as NOUNs due to comma punctuation.
        """
        verbs = []
        for token in sent:
            if token.pos_ == "VERB":
                verbs.append(token)
            elif token.pos_ == "NOUN" and token.dep_ == "conj" and token.head.pos_ == "VERB":
                # Ensure it sits inside a serial structure surrounded by commas or conjunctions
                has_coord_sibling = any(c.pos_ == "VERB" or c.text == "and" for c in token.children)
                if has_coord_sibling or any(c.text == "," for c in token.head.children):
                    token.pos_ = "VERB"  # Safe in-memory override for this parsing run
                    verbs.append(token)
        return verbs