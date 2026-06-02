from datetime import datetime
from typing import List, Any
import spacy

from app.schemas.extracted_actions import ExtractedActionPrediction
from app.models.action_extractor.components.action_detector import ActionDetector
from app.models.action_extractor.components.ownership_detector import OwnershipDetector


class ActionParser:
    TARGET_DEPS = {"dobj", "obj", "pobj", "attr", "nsubjpass"}
    MODAL_VERBS = {"need", "want", "try", "go", "have", "must", "should"}
    PURPOSE_ANCHORS = {
        "to", "so", "such", "thereby", "thus", "meaning", "so that",
        "before", "after", "until"
    }
    STRUCTURAL_TRANSITIONS = {
        "and", "but", "then", "or", "yet", "so that",
        "before", "after", "until"
    }

    def __init__(self):
        pass

    @classmethod
    def parse_action_phrases(cls, doc) -> List[ExtractedActionPrediction]:
        extracted_actions: List[ExtractedActionPrediction] = []

        # Instantiate our structural component layers
        detector = ActionDetector()
        ownership = OwnershipDetector()

        for sent in doc.sents:
            # Sentence level parsing variables
            deadline = None  # Deadline extracted in deadline_normalizer downstream
            raw_entities_list = [{"text": ent.text, "label": ent.label_} for ent in sent.ents]

            # Collect every verb token present within this sentence slice
            verbs = [t for t in sent if t.pos_ == "VERB"]

            for verb in verbs:
                # LAYER 1: Is this specific token an actionable directive?
                if not detector.is_actionable_verb(verb, sent):
                    continue

                # LAYER 2: Is this specific verb assigned to me?
                if not ownership.is_verb_assigned_to_me(verb):
                    continue

                # LAYER 3: Purpose/Background Clause Isolation Guard
                if cls._is_trapped_in_purpose_clause(sent, verb, verbs):
                    continue

                verb_lemma = verb.lemma_.lower()

                # Skip "regarding" functioning as a pseudo-preposition
                if verb_lemma == "regard" or verb.text.lower() == "regarding":
                    continue

                # Robust structural filtering for modal/auxiliary headers
                if verb_lemma in cls.MODAL_VERBS:
                    has_xcomp_relation = any(c.dep_ in {"xcomp", "ccomp"} for c in verb.subtree if c != verb)
                    if has_xcomp_relation or verb.dep_ == "aux":
                        continue

                # Locate direct target nouns bound immediately to this specific verb
                direct_objects = [c for c in verb.children if c.dep_ in cls.TARGET_DEPS]

                # Check the entire subtree for passive subjects (nsubjpass)
                if not direct_objects:
                    passive_targets = [t for t in verb.subtree if t.dep_ == "nsubjpass"]
                    if passive_targets:
                        direct_objects = passive_targets

                # --- UNIFIED COORDINATION OBJECT HARMONIZATION ---
                # Resolves the middle-node regression for complex chains like: "review, approve, and return the proposal"
                if not direct_objects:
                    # 1. Locate the absolute structural head verb of this local coordinate family
                    root_verb = verb
                    while root_verb.dep_ == "conj" and root_verb.head.pos_ == "VERB" and root_verb != root_verb.head:
                        root_verb = root_verb.head

                    # 2. Extract every single verb token tied together in this specific family
                    coordinate_family = [t for t in root_verb.subtree if t.dep_ == "conj" and t.pos_ == "VERB"]
                    coordinate_family.append(root_verb)

                    # 3. Scan the entire family. The moment ANY sibling possesses a valid direct object target,
                    # inherit it immediately. This guarantees flawless multi-verb target synchronization.
                    for sibling in coordinate_family:
                        sibling_objects = [c for c in sibling.children if c.dep_ in cls.TARGET_DEPS]
                        if sibling_objects:
                            direct_objects = sibling_objects
                            break

                # Extract and unroll primary targets along with compound conjunction targets
                all_objects = []
                for dobj in direct_objects:
                    # Ignore weak placeholder pronouns if alternative noun components exist
                    if dobj.pos_ == "PRON" and dobj.text.lower() in {"this", "it", "them"} and len(direct_objects) > 1:
                        continue
                    all_objects.append(dobj)
                    conjuncts = [c for c in dobj.subtree if c.dep_ == "conj" and c.pos_ in ["NOUN", "PROPN"]]
                    all_objects.extend(conjuncts)

                # 2. Build & Emit Valid Predictive Outputs
                if all_objects:
                    for obj_token in all_objects:
                        # CRITICAL REGRESSION FIX: Use exact literal text (.text) instead of .lemma_
                        # to safeguard plurals like "details" or "credentials" from getting forced to singular forms.
                        base_obj_text = obj_token.text.lower()

                        # Hardened lefts check: Safely gather prefix descriptors ("ssl", "staging")
                        # while completely ignoring right-side trailing prepositional overflow ("with the client").
                        left_compounds = [t.text.lower() for t in obj_token.lefts if t.dep_ in {"compound", "amod"}]
                        if left_compounds:
                            full_obj_text = f"{' '.join(left_compounds)} {base_obj_text}".strip()
                        else:
                            full_obj_text = base_obj_text

                        # Anaphora pronoun fallback context resolution
                        if full_obj_text in {"it", "them", "this", "that"} and len(extracted_actions) > 0:
                            if extracted_actions[-1].object_primitive:
                                full_obj_text = extracted_actions[-1].object_primitive

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
        """
        Hybrid Gate: Combines structural dependency tags with a dynamic, punctuation-
        independent look-back window built from the position of the preceding verb.
        """
        # Skip lookup if it's a primary structural task/action verb
        if verb.dep_ not in {"advcl", "xcomp"}:
            return False

        # 2. DYNAMIC BOUNDARY: Find the previous action verb in this sentence loop
        # Default to sentence start (0) if this is the first verb being processed
        prev_verb_sent_idx = 0
        try:
            current_idx = verbs_list.index(verb)
            if current_idx > 0:
                prev_verb = verbs_list[current_idx - 1]
                # Start our look-back window right AFTER the previous verb
                prev_verb_sent_idx = prev_verb.i - sent.start + 1
        except ValueError:
            pass

        # 3. Extract tokens strictly spanning between the previous verb and current verb
        raw_prev = [t.text.lower() for t in sent[prev_verb_sent_idx: verb.i - sent.start]]
        if not raw_prev:
            return False

        # 4. CONJUNCTION & TRANSITION RESET: Break history on transition words
        # Set index to i (instead of i + 1) to keep the marker inside the window for validation
        start_idx = 0
        for i, token in enumerate(raw_prev):
            if token in cls.STRUCTURAL_TRANSITIONS:
                start_idx = i

        # 5. DYNAMIC WINDOW SPLICING
        local_window = raw_prev[start_idx:]

        # 6. VERDICT: If a purpose/result anchor lives in this clause window, it's noise.
        if any(anchor in local_window for anchor in cls.PURPOSE_ANCHORS):
            return True  # Trapped noise, safely drop it.

        return False  # FIXED: Tuple comma removed. Correctly returns boolean primitive.