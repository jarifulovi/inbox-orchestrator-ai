from datetime import datetime
from typing import List
import spacy

from app.schemas.extracted_actions import ExtractedActionPrediction
from app.models.action_extractor.components.action_detector import ActionDetector
from app.models.action_extractor.components.ownership_detector import OwnershipDetector


class ActionParser:
    def __init__(self):
        pass

    @staticmethod
    def parse_action_phrases(doc) -> List[ExtractedActionPrediction]:
        extracted_actions: List[ExtractedActionPrediction] = []

        # Instantiate our structural layers
        detector = ActionDetector()
        ownership = OwnershipDetector()

        TARGET_DEPS = {"dobj", "obj", "pobj", "attr", "nsubjpass"}
        MODAL_VERBS = {"need", "want", "try", "go", "have", "must", "should"}

        for sent in doc.sents:

            # LAYER 1: Action Detection Gatekeeper
            if not detector.is_actionable_sentence(sent):
                continue

            # LAYER 2: Ownership Verification Gatekeeper
            if not ownership.is_assigned_to_me(sent):
                continue

            # -------------------------------------------------------------
            # DECISION PASS: If it reaches here, it is a highly targeted,
            # verified action assigned to "me". Now run granular extraction.
            # -------------------------------------------------------------
            deadline = None
            raw_entities_list = [{"text": ent.text, "label": ent.label_} for ent in sent.ents]

            # 1. Extract Valid Action Verbs
            verbs = [t for t in sent if t.pos_ == "VERB"]

            for verb in verbs:
                verb_lemma = verb.lemma_.lower()

                # Skip "regarding" functioning as a pseudo-preposition
                if verb_lemma == "regard" or verb.text.lower() == "regarding":
                    continue

                # Robust structural filtering for modal/auxiliary headers
                if verb_lemma in MODAL_VERBS:
                    has_xcomp_relation = any(c.dep_ in {"xcomp", "ccomp"} for c in verb.subtree if c != verb)
                    if has_xcomp_relation or verb.dep_ == "aux":
                        continue

                # Find direct target nouns bound immediately to this specific verb
                direct_objects = [c for c in verb.children if c.dep_ in TARGET_DEPS]

                # Check the entire subtree for passive subjects (nsubjpass)
                if not direct_objects:
                    passive_targets = [t for t in verb.subtree if t.dep_ == "nsubjpass"]
                    if passive_targets:
                        direct_objects = passive_targets

                # FIX PATH A: Verb is a conjunct downstream inheriting parent context
                if not direct_objects and verb.dep_ == "conj" and verb.head.pos_ == "VERB":
                    direct_objects = [c for c in verb.head.children if c.dep_ in TARGET_DEPS]

                # FIX PATH B: Verb is the parent head stealing from a conjunct sibling
                if not direct_objects:
                    for sibling in verb.children:
                        if sibling.dep_ == "conj" and sibling.pos_ == "VERB":
                            sibling_objects = [c for c in sibling.children if c.dep_ in TARGET_DEPS]
                            if sibling_objects:
                                direct_objects = sibling_objects
                                break

                # Extract and unroll primary targets along with compound conjunction targets
                all_objects = []
                for dobj in direct_objects:
                    all_objects.append(dobj)
                    conjuncts = [c for c in dobj.subtree if c.dep_ == "conj" and c.pos_ in ["NOUN", "PROPN"]]
                    all_objects.extend(conjuncts)

                # 2. Build & Emit Valid Predictive Outputs
                if all_objects:
                    for obj_token in all_objects:
                        # Build smart modifiers context
                        modifiers = [t.text for t in obj_token.children if t.dep_ in {"prep", "amod", "compound"}]
                        if modifiers and obj_token.dep_ != "conj":
                            full_obj_text = f"{obj_token.lemma_.lower()} {' '.join([t.lemma_.lower() for t in obj_token.rights if t.dep_ in {'prep', 'dobj'} or t.pos_ == 'NOUN'])}".strip()
                        else:
                            full_obj_text = obj_token.lemma_.lower()

                        action_prediction = ExtractedActionPrediction(
                            verb_primitive=verb.lemma_.lower(),
                            object_primitive=full_obj_text if full_obj_text else obj_token.lemma_.lower(),
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