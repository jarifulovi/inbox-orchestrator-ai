from spacy.language import Language
from spacy.tokens import Doc
from app.core.ml_models.fact_extractor.fact_parser import FactParser

# Define a custom attribute extension on spaCy's native Doc class
# This allows us to access results using doc._.email_facts later
if not Doc.has_extension("email_facts"):
    Doc.set_extension("email_facts", default=[])


@Language.factory("fact_extractor_component")
def create_fact_extractor(nlp, name):
    return FactExtractorComponent()


class FactExtractorComponent:
    def __call__(self, doc: Doc) -> Doc:
        # Run our parsing logic against the current text document
        facts = FactParser.parse_facts(doc)

        # Store the findings inside the custom spaCy extension slot
        doc._.email_facts = facts
        return doc
