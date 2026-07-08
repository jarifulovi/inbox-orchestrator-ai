import spacy
from typing import cast, List, Dict, Any
from uuid import UUID
from datetime import datetime

# Import spacy_engine to register the component factory
import app.core.ml_models.fact_extractor.spacy_engine
from app.core.schemas.email_facts import EmailFactBatchResponse, EmailFactPredictionDict
from app.core.ml_models.fact_extractor.components.deadline_normalizer import DeadlineNormalizer
from app.core.ml_models.fact_extractor.components.processors import TextPreprocessor, FactPostprocessor


class FactExtractor:
    def __init__(self):
        # Load the lightweight English model framework
        self.nlp = spacy.load("en_core_web_sm")

        # Append the custom logic component directly to the end of spaCy's pipeline
        self.nlp.add_pipe("fact_extractor_component", last=True)

    def predict(
            self,
            safe_nodes: List[Dict[str, Any]],
            batch_size: int = 32
    ) -> List[EmailFactBatchResponse]:
        """Processes safe nodes and returns a dense array of envelope records matching len(safe_nodes)."""

        cleaned_pairs = [
            (TextPreprocessor.clean(node.get("cleaned_body", "")), node.get("id"))
            for node in safe_nodes
        ]

        dense_results: List[EmailFactBatchResponse] = []

        # Execute your optimized spaCy pipe stream
        for doc, raw_email_id in self.nlp.pipe(
                cleaned_pairs,
                as_tuples=True,
                batch_size=batch_size,
                disable=["ner"]
        ):
            email_id: UUID = cast(UUID, raw_email_id)

            try:
                # 1. Retrieve the parsed facts from custom extension slot
                raw_facts = getattr(doc._, "email_facts", [])
                
                # Copy raw facts to avoid mutating default shared lists
                raw_facts_copied = [dict(f) for f in raw_facts]

                # 2. Enrich with deadlines
                enriched_facts = DeadlineNormalizer.normalize_deadlines(raw_facts_copied)

                # 3. Postprocess (clean & sanitize & deduplicate)
                final_facts_list: List[Dict[str, Any]] = FactPostprocessor.process(enriched_facts)

            except Exception as e:
                print(f"[ML SERVICE ERROR] FactExtractor item failure for email {email_id}: {e}")
                final_facts_list = []

            # 4. Construct your envelope mapping perfectly to EmailFactBatchResponse
            envelope: EmailFactBatchResponse = {
                "email_id": str(email_id),
                "facts": cast(List[EmailFactPredictionDict], final_facts_list)
            }

            dense_results.append(envelope)

        return dense_results


# Quick self-contained execution script for testing local workflows
if __name__ == "__main__":
    import json
    from uuid import uuid4
    
    pipeline = FactExtractor()

    test_emails = [
        {
            "id": uuid4(),
            "cleaned_body": "Please print the quarter report by Friday. I will send you the credentials tomorrow. Did you get the email? We decided to start the project."
        }
    ]

    results = pipeline.predict(test_emails)
    print(json.dumps(results, indent=2))
