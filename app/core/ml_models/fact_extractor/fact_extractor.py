import spacy
from typing import cast, List, Dict, Any
from uuid import UUID
from datetime import datetime

# Import spacy_engine to register the component factory
import app.core.ml_models.fact_extractor.spacy_engine
from app.core.schemas.email_facts import EmailFactBatchResponse, EmailFactPredictionDict
from app.core.ml_models.fact_extractor.components.deadline_normalizer import DeadlineNormalizer
from app.core.ml_models.fact_extractor.components.processors import TextPreprocessor, FactPostprocessor


from app.core.ml_models.fact_extractor.components.email_filter import EmailFilter
from app.core.ml_models.fact_extractor.components.type_checker import FactTypeChecker


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

        non_bypassed_nodes = []
        bypassed_indices = {}

        # 1. Email Filter Layer: Pre-filtering bypassed category emails
        for i, node in enumerate(safe_nodes):
            category = node.get("category")
            payload = node.get("raw_payload") or {}
            label_ids = payload.get("labelIds") or []
            if EmailFilter.should_bypass_extraction(category, label_ids):
                bypassed_indices[i] = []
            else:
                non_bypassed_nodes.append((i, node))

        cleaned_pairs = [
            (
                TextPreprocessor.clean(node.get("cleaned_body", "")),
                (i, node.get("id"), node.get("category"))
            )
            for i, node in non_bypassed_nodes
        ]

        dense_results_map = {}

        if cleaned_pairs:
            # Execute optimized spaCy pipe stream only for non-bypassed nodes
            for doc, context in self.nlp.pipe(
                    cleaned_pairs,
                    as_tuples=True,
                    batch_size=batch_size,
                    disable=["ner"]
            ):
                idx, raw_email_id, category = context
                email_id = cast(UUID, raw_email_id)

                try:
                    # Retrieve the parsed facts from custom extension slot
                    raw_facts = getattr(doc._, "email_facts", [])
                    
                    # Copy raw facts to avoid mutating default shared lists
                    raw_facts_copied = [dict(f) for f in raw_facts]

                    # 2. Enrich with deadlines
                    enriched_facts = DeadlineNormalizer.normalize_deadlines(raw_facts_copied)

                    # 3. Postprocess (clean & sanitize & deduplicate)
                    post_processed = FactPostprocessor.process(enriched_facts)

                    # 4. Fact Type Checker Layer: Validate type assignments and filter out noise
                    validated_facts = FactTypeChecker.validate_fact_types(post_processed)

                    # 5. Email Filter Layer: Filter final fact types allowed for this category
                    final_facts_list = EmailFilter.filter_extracted_facts(category, validated_facts)

                except Exception as e:
                    print(f"[ML SERVICE ERROR] FactExtractor item failure for email {email_id}: {e}")
                    final_facts_list = []

                dense_results_map[idx] = {
                    "email_id": str(email_id),
                    "facts": cast(List[EmailFactPredictionDict], final_facts_list)
                }

        # Populate bypassed items in the map
        for idx in bypassed_indices:
            node = safe_nodes[idx]
            dense_results_map[idx] = {
                "email_id": str(node.get("id")),
                "facts": []
            }

        # Return results in the exact original order
        return [dense_results_map[i] for i in range(len(safe_nodes))]


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
