from typing import cast
from uuid import UUID
from datetime import datetime
from app.core.schemas.extracted_actions import ExtractedActionPrediction, ExtractedActionBatchResponse
from app.core.models.action_extractor.components.deadline_normalizer import DeadlineNormalizer
from app.core.models.action_extractor.components.processors import TextPreprocessor, ActionPostprocessor




class ActionExtractor:
    def __init__(self):
        # Load the lightweight English model framework
        self.nlp = spacy.load("en_core_web_sm")

        # Append the custom logic component directly to the end of spaCy's pipeline
        self.nlp.add_pipe("action_extractor_component", last=True)

    def predict(
            self,
            safe_nodes: list[dict],
            batch_size: int = 32
    ) -> list[ExtractedActionBatchResponse]:
        """Processes safe nodes and returns a dense array of envelope records matching len(safe_nodes)."""

        cleaned_pairs = [
            (TextPreprocessor.clean(node.get("cleaned_body", "")), node.get("id"))
            for node in safe_nodes
        ]

        dense_results: list[ExtractedActionBatchResponse] = []

        # Execute your optimized spaCy pipe stream
        for doc, raw_email_id in self.nlp.pipe(
                cleaned_pairs,
                as_tuples=True,
                batch_size=batch_size,
                disable=["ner"]
        ):
            # 1. Cast the 'Any' context token from spaCy explicitly to UUID to satisfy the linter
            email_id: UUID = cast(UUID, raw_email_id)

            try:
                raw_actions = doc._.extracted_actions
                enriched_actions = DeadlineNormalizer.normalize_action_deadlines(raw_actions)
                final_actions_list: list[ExtractedActionPrediction] = ActionPostprocessor.process(enriched_actions)

            except Exception as e:
                print(f"[ML SERVICE ERROR] ActionExtractor item failure for email {email_id}: {e}")
                final_actions_list = []

            serialized_actions: list[ExtractedActionPrediction] = []
            for action in final_actions_list:
                # Safely modify the field in-place
                value = action["parsed_deadline"]
                if isinstance(value, datetime):
                    action["parsed_deadline"] = value.isoformat()
                else:
                    action["parsed_deadline"] = None

                serialized_actions.append(action)

            # 3. Construct your envelope mapping perfectly to ExtractedActionBatchResponse
            envelope: ExtractedActionBatchResponse = {
                "email_id": email_id,
                "actions": serialized_actions
            }

            dense_results.append(envelope)

        return dense_results



import json
from uuid import uuid4
# Quick self-contained execution script for testing local workflows
if __name__ == "__main__":
    pipeline = ActionExtractor()


    test_task_emails = [
        # Category 1: Direct Imperatives / Absolute Commands
        # (Should extract: verb="print", object="report", deadline=None)
        (
            uuid4(),
            "Please print the quarter report and place it on my desk before you leave today."
        ),

        # Category 2: Immediate Urgency Cues
        # (Should extract: verb="call", object="client", deadline=datetime.now())
        (
            uuid4(),
            "You need to call the enterprise client right now to resolve their payment issue."
        ),

        # Category 3: Explicit Target Date Deadlines
        # (Should extract: verb="submit", object="invoice", deadline=June 5, 2026 at midnight)
        (
            uuid4(),
            "Make sure you submit the vendor invoice by June 5th so accounting can process it on time."
        ),

        # Category 4: First-Person Plural Obligations (Shared Team Tasks)
        # (Should extract: verb="update", object="documentation", deadline=None)
        (
            uuid4(),
            "We must update our internal API documentation before the integration branch is merged."
        ),

        # Category 5: Multi-Task Sentences (Compound Direct Objects)
        # (Should extract two items: 1. verb="review", object="contract" | 2. verb="review", object="proposal")
        (
            uuid4(),
            "Please review the employment contract and the project proposal as soon as possible."
        )
    ]


    converted_emails = test_task_emails
    results = pipeline.predict(converted_emails)

    for result in results:
        # 1. Convert the predictions inside the batch response into JSON-safe dictionaries
        serializable_actions = [action.model_dump(mode="json") for action in result.actions]

        print(f"\n=========================================")
        print(f"Email ID: {result.email_id}")
        print(f"=========================================")

        # 2. Check if this email actually produced any actionable tasks
        if serializable_actions:
            # Safely grab the text from the first discovered task's source sentence
            print(f"Sample Sentence Match: '{serializable_actions[0]['source_sentence']}'")
            print(f"Extracted Tasks ({len(serializable_actions)} found):")
            print(json.dumps(serializable_actions, indent=2))
        else:
            print("Status: No actionable tasks detected for 'me' in this email. []")


import spacy


if __name__ == "__main__":
    nlp = spacy.load("en_core_web_sm")
    text = "Transfer the unallocated funds to escrow so accounting can balance the ledger sheets."
    doc = nlp(text)

    print(f"{'TOKEN':<12} | {'POS':<6} | {'DEP':<10} | {'HEAD':<12} | {'CHILDREN'}")
    print("-" * 60)
    for token in doc:
        children = [c.text for c in token.children]
        print(f"{token.text:<12} | {token.pos_:<6} | {token.dep_:<10} | {token.head.text:<12} | {children}")