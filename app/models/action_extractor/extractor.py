import json
from typing import List
from uuid import UUID, uuid4
import spacy

from app.schemas.extracted_actions import ExtractedActionBatchResponse
from app.models.action_extractor.components.deadline_normalizer import DeadlineNormalizer
from app.models.action_extractor.spacy_engine import create_action_extractor
from app.models.action_extractor.components.processors import TextPreprocessor, ActionPostprocessor


class ActionExtractor:
    def __init__(self):
        # Load the lightweight English model framework
        self.nlp = spacy.load("en_core_web_sm")

        # Append the custom logic component directly to the end of spaCy's pipeline
        self.nlp.add_pipe("action_extractor_component", last=True)


    def process_emails_bulk(
            self,
            emails: List[tuple[UUID, str]],  # Input format: [(email_id, body), (email_id, body)]
            batch_size: int = 32
    ) -> List[ExtractedActionBatchResponse]:


        cleaned_pairs = [(TextPreprocessor.clean(body), email_id) for email_id, body in emails]
        bulk_responses: List[ExtractedActionBatchResponse] = []

        for doc, email_id in self.nlp.pipe(cleaned_pairs, as_tuples=True, batch_size=batch_size):
            raw_actions = doc._.extracted_actions
            enriched_actions = DeadlineNormalizer.normalize_action_deadlines(raw_actions)
            final_actions = ActionPostprocessor.process(enriched_actions)

            batch_response = ExtractedActionBatchResponse(
                email_id=email_id,
                actions=final_actions
            )

            bulk_responses.append(batch_response)

        return bulk_responses






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
    results = pipeline.process_emails_bulk(converted_emails)

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