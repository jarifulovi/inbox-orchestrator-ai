from spacy.language import Language
from spacy.tokens import Doc
from app.models.action_extractor.action_parser import ActionParser

# Define a custom attribute extension on spaCy's native Doc class
# This allows us to access results using doc._.extracted_actions later
if not Doc.has_extension("extracted_actions"):
    Doc.set_extension("extracted_actions", default=[])


@Language.factory("action_extractor_component")
def create_action_extractor(nlp, name):
    return ActionExtractorComponent()


class ActionExtractorComponent:
    def __call__(self, doc: Doc) -> Doc:
        # Run our parsing logic against the current text document
        actions = ActionParser.parse_action_phrases(doc)

        # Store the findings inside the custom spaCy extension slot
        doc._.extracted_actions = actions
        return doc