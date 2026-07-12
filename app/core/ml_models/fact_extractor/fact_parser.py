from typing import List, Dict, Any, Set
from spacy.tokens import Token, Span

from app.core.ml_models.fact_extractor.components.action_detector import ActionDetector
from app.core.ml_models.fact_extractor.components.ownership_detector import OwnershipDetector


class FactParser:
    TARGET_DEPS = {"dobj", "obj", "pobj", "attr", "nsubjpass"}
    MODAL_VERBS = {"need", "want", "try", "go", "have", "must", "should", "remember"}
    PURPOSE_ANCHORS = {"to", "so", "such", "thereby", "thus", "meaning"}
    STRUCTURAL_TRANSITIONS = {"and", "but", "then", "or", "yet", "so"}
    
    DECISION_VERBS = {"decide", "agree", "resolve", "conclude", "settle", "determine"}
    DECISION_NOUNS = {"decision", "agreement", "resolution"}

    def __init__(self):
        pass

    @classmethod
    def parse_facts(cls, doc) -> List[Dict[str, Any]]:
        extracted_facts: List[Dict[str, Any]] = []

        action_detector = ActionDetector()
        ownership_detector = OwnershipDetector()

        for sent_idx, sent in enumerate(doc.sents):
            # 1. Base Entity Extraction
            entities_dict: Dict[str, List[str]] = {
                "PERSON": [],
                "ORG": [],
                "PRODUCT": []
            }
            raw_entities_list = []
            for ent in sent.ents:
                label = ent.label_
                text = ent.text.strip()
                raw_entities_list.append({"text": text, "label": label})
                if label in entities_dict:
                    entities_dict[label].append(text)
                else:
                    # Allow dynamic entity keys too
                    entities_dict.setdefault(label, []).append(text)

            # Heuristic stage for verbs
            verbs = cls._heal_misclassified_serial_verbs(sent)
            verbs = cls._heal_misclassified_imperatives(sent, verbs)

            # Identify if there are any tasks or commitments in this sentence
            sentence_tasks_or_commitments = []

            for verb in verbs:
                if verb.dep_ in {"amod", "nmod"}:
                    continue
                if not action_detector.is_actionable_verb(verb, sent):
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

                # Determine ownership
                actor = ownership_detector.determine_subject_actor(verb)
                fact_type = "task" if actor == "recipient" else "commitment"

                # Find direct/indirect objects
                direct_objects = [c for c in verb.children if c.dep_ in cls.TARGET_DEPS]
                if not direct_objects:
                    passive_targets = [t for t in verb.subtree if t.dep_ == "nsubjpass"]
                    if passive_targets:
                        direct_objects = passive_targets

                # Coord sibling inheritance
                if not direct_objects:
                    root_verb = verb
                    while root_verb.dep_ == "conj" and root_verb.head.pos_ == "VERB" and root_verb != root_verb.head:
                        root_verb = root_verb.head

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

                # Map objects to actions
                if all_objects:
                    for obj_token in all_objects:
                        full_obj_text = cls._compile_object_phrase(obj_token, doc)

                        # Anaphora resolution
                        if full_obj_text in {"it", "them", "this", "that", "both"} and len(sentence_tasks_or_commitments) > 0:
                            for prev_act in reversed(sentence_tasks_or_commitments):
                                prev_payload = prev_act.get("payload", {})
                                if prev_payload.get("object") and prev_payload.get("object") not in {"it", "them", "this", "that", "both"}:
                                    full_obj_text = prev_payload.get("object")
                                    break

                        sentence_tasks_or_commitments.append({
                            "sentence_index": sent_idx,
                            "fact_type": fact_type,
                            "payload": {
                                "action": verb_lemma,
                                "object": full_obj_text,
                                "actor": actor,
                                "raw_temporal_hint": None,
                                "entities": entities_dict
                            },
                            "source_sentence": sent.text.strip(),
                            "confidence": 0.90,
                            "model_version": "fact_extractor_v1"
                        })
                else:
                    sentence_tasks_or_commitments.append({
                        "sentence_index": sent_idx,
                        "fact_type": fact_type,
                        "payload": {
                            "action": verb_lemma,
                            "object": None,
                            "actor": actor,
                            "raw_temporal_hint": None,
                            "entities": entities_dict
                        },
                        "source_sentence": sent.text.strip(),
                        "confidence": 0.85,
                        "model_version": "fact_extractor_v1"
                    })

            # If tasks/commitments were found, add them
            if sentence_tasks_or_commitments:
                extracted_facts.extend(sentence_tasks_or_commitments)
                continue

            # 2. Question Classification
            sent_text = sent.text.strip()
            if sent_text.endswith("?") or "?" in sent_text:
                # Find if direct target is "you"
                actor = "recipient" if any(t.text.lower() == "you" for t in sent) else "sender"
                extracted_facts.append({
                    "sentence_index": sent_idx,
                    "fact_type": "question",
                    "payload": {
                        "action": None,
                        "object": None,
                        "actor": actor,
                        "raw_temporal_hint": None,
                        "entities": entities_dict
                    },
                    "source_sentence": sent_text,
                    "confidence": 0.95,
                    "model_version": "fact_extractor_v1"
                })
                continue

            # 3. Decision Classification
            is_decision = False
            decision_actor = "team"
            
            # Check decision words or trigger phrases
            sent_text_lower = sent_text.lower()
            if any(word in sent_text_lower for word in {"we decided", "we agreed", "we have agreed", "team decided", "agreed that", "decided that"}):
                is_decision = True
                decision_actor = "both"
            else:
                for token in sent:
                    if token.lemma_.lower() in cls.DECISION_VERBS and token.pos_ == "VERB":
                        is_decision = True
                        # check subject pronoun
                        for c in token.children:
                            if c.dep_ in {"nsubj", "nsubjpass"}:
                                if c.text.lower() in {"i", "we", "team"}:
                                    decision_actor = "both"
                                elif c.text.lower() == "you":
                                    decision_actor = "recipient"
                        break
                    elif token.text.lower() in cls.DECISION_NOUNS and token.pos_ == "NOUN":
                        is_decision = True
                        break

            if is_decision:
                # Try to extract the action and object of the decision
                decision_verb_lemma = None
                decision_obj = None
                for token in sent:
                    if token.lemma_.lower() in cls.DECISION_VERBS and token.pos_ == "VERB":
                        decision_verb_lemma = token.lemma_.lower()
                        # Check for nested action (e.g. "decided to deploy")
                        xcomp_verbs = [c for c in token.children if c.dep_ == "xcomp" and c.pos_ == "VERB"]
                        if xcomp_verbs:
                            target_verb = xcomp_verbs[0]
                            decision_verb_lemma = target_verb.lemma_.lower()
                            d_objs = [c for c in target_verb.children if c.dep_ in cls.TARGET_DEPS]
                            if d_objs:
                                decision_obj = cls._compile_object_phrase(d_objs[0], doc)
                        else:
                            d_objs = [c for c in token.children if c.dep_ in cls.TARGET_DEPS]
                            if d_objs:
                                decision_obj = cls._compile_object_phrase(d_objs[0], doc)
                        break

                extracted_facts.append({
                    "sentence_index": sent_idx,
                    "fact_type": "decision",
                    "payload": {
                        "action": decision_verb_lemma,
                        "object": decision_obj,
                        "actor": decision_actor,
                        "raw_temporal_hint": None,
                        "entities": entities_dict
                    },
                    "source_sentence": sent_text,
                    "confidence": 0.85,
                    "model_version": "fact_extractor_v1"
                })
                continue

            # 4. Fallback Fact Classification
            extracted_facts.append({
                "sentence_index": sent_idx,
                "fact_type": "fact",
                "payload": {
                    "action": None,
                    "object": None,
                    "actor": "third-party",
                    "raw_temporal_hint": None,
                    "entities": entities_dict
                },
                "source_sentence": sent_text,
                "confidence": 0.70,
                "model_version": "fact_extractor_v1"
            })

        return extracted_facts

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

        local_tokens = sent[prev_verb_sent_idx: verb.i - sent.start]
        if not local_tokens:
            return False

        start_idx = 0
        for i, token in enumerate(local_tokens):
            t_text = token.text.lower()

            if t_text in cls.STRUCTURAL_TRANSITIONS:
                if t_text == "so" and i + 1 < len(local_tokens) and local_tokens[i + 1].text.lower() == "that":
                    start_idx = i + 1
                else:
                    start_idx = i

        window_tokens = local_tokens[start_idx:]

        for i, token in enumerate(window_tokens):
            t_text = token.text.lower()
            if t_text in cls.PURPOSE_ANCHORS:
                return True

        return False

    @classmethod
    def _heal_misclassified_serial_verbs(cls, sent) -> List[Token]:
        verbs = []
        for token in sent:
            if token.pos_ == "VERB":
                verbs.append(token)
            elif token.pos_ == "NOUN" and token.dep_ == "conj" and token.head.pos_ == "VERB":
                has_coord_sibling = any(c.pos_ == "VERB" or c.text == "and" for c in token.children)
                if has_coord_sibling or any(c.text == "," for c in token.head.children):
                    token.pos_ = "VERB"
                    verbs.append(token)
        return verbs

    @classmethod
    def _heal_misclassified_imperatives(cls, sent, current_verbs: List[Token]) -> List[Token]:
        imperative_actions = {
            "forward", "route", "pass", "send", "transfer", "ship",
            "assign", "delegate", "appoint", "nominate"
        }

        for token in sent:
            if token.pos_ == "ADV" and token.dep_ == "ROOT":
                token_text = token.text.lower()
                token_lemma = token.lemma_.lower()

                if token_text in imperative_actions or token_lemma in imperative_actions:
                    has_objects = any(c.dep_ in cls.TARGET_DEPS or c.dep_ == "prep" for c in token.children)

                    if has_objects:
                        token.pos_ = "VERB"
                        token.tag_ = "VB"

                        if token not in current_verbs:
                            current_verbs.append(token)

        return current_verbs

    @classmethod
    def _compile_object_phrase(cls, obj_token, doc) -> str:
        base_obj_text = obj_token.text.lower()
        
        # Recursive collection of left-side modifiers (compounds, adjectives, noun modifiers)
        left_tokens_list = []
        def collect_left_modifiers(tok):
            for child in tok.lefts:
                if child.dep_ in {"compound", "amod", "nmod"}:
                    collect_left_modifiers(child)
                    left_tokens_list.append(child)
        
        collect_left_modifiers(obj_token)
        left_tokens = sorted(left_tokens_list, key=lambda x: x.i)
        
        left_compounds = []
        for lt in left_tokens:
            if lt.i + 1 < len(doc) and doc[lt.i + 1].text == "-":
                hyphenated_term = f"{lt.text}-{doc[lt.i + 2].text}" if lt.i + 2 < len(doc) else lt.text
                left_compounds.append(hyphenated_term.lower())
            elif lt.text == "-" or (lt.i - 1 >= 0 and doc[lt.i - 1].text == "-"):
                continue
            else:
                left_compounds.append(lt.text.lower())

        if left_compounds:
            return f"{' '.join(left_compounds)} {base_obj_text}".strip()
        return base_obj_text

