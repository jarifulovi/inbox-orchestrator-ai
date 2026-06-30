import json
from datetime import datetime, timezone
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import ExtractedTaskBlueprint

class TaskGenerationService:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def _build_generation_prompt(self, action_data: dict, email_body: str) -> str:
        """Constructs a context-dense prompt for Gemini to generate a task blueprint."""
        return f"""
You are an advanced AI assistant tasked with generating a structured task blueprint based on an email context and a pre-extracted action item.

Here is the email body:
---
{email_body}
---

Here is the extracted action item data:
---
{json.dumps(action_data, indent=2)}
---

Your Goal:
Extract and determine the core details for a clear, actionable task blueprint according to the following rules:
- Determine is_actionable_task: Evaluate if this action should actually become a task. Mark it true only if it is a concrete, uncompleted action the user must perform. Mark false if it's purely informational, overly vague, noise or already resolved in the email.
- Provide an actionable and clear title.
- Determine the priority (high, medium, low) based on the urgency conveyed in the email or action.
- Create an action_fingerprint: a unique 3-5 word deterministic identifier (e.g., 'invoice_payment_followup'). You MUST standardize these (use snake_case, generic verbs/nouns) so similar actions receive the exact same fingerprint.
- Determine due_date_days_from_now: The number of days from today this task should be due based on the email context, or null if no deadline is specified.
"""

    def generate_task(self, action_data: dict, email_body: str) -> ExtractedTaskBlueprint | None:
        """
        Coordinates the LLM context evaluation to generate a task blueprint from an extracted action.
        """
        if not action_data or not email_body:
            return None

        prompt = self._build_generation_prompt(action_data, email_body)
        
        try:
            # Call the generic engine and enforce strict pydantic output
            blueprint: ExtractedTaskBlueprint = self.llm.generate_structured_json(
                prompt=prompt, 
                response_schema=ExtractedTaskBlueprint
            )
            return blueprint
        except Exception as e:
            print(f"[TaskGenerationService] Failed to generate task blueprint: {e}")
            return None
