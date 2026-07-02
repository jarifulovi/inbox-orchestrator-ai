import json
import hashlib
from datetime import datetime, timezone
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import BatchExtractedTaskBlueprint

class TaskGenerationService:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate_action_fingerprint(self, thread_id: str, verb_primitive: str, object_primitive: str) -> str:
        """Generates a deterministic MD5 fingerprint for a task based on thread and action semantics."""
        raw_string = f"{thread_id}_{verb_primitive}_{object_primitive}".lower()
        return hashlib.md5(raw_string.encode('utf-8')).hexdigest()

    def _build_batch_generation_prompt(self, actions_data: list[dict]) -> str:
        """Constructs a context-dense prompt for Gemini to generate task blueprints in batch."""
        return f"""
You are an advanced AI assistant tasked with generating structured task blueprints based on a batch of pre-extracted action items.

Here is the batch of extracted action items (JSON format):
---
{json.dumps(actions_data, indent=2)}
---

Your Goal:
Extract and determine the core details for clear, actionable task blueprints for each item in the batch according to the following rules:
- Evaluate each action independently and include its corresponding `extracted_action_id` in your response.
- Determine is_actionable_task: Evaluate if this action should actually become a task. Mark it true only if it is a concrete, uncompleted action the user must perform. Mark false if it's purely informational, overly vague, noise or already resolved.
- Provide an actionable and clear title.
- Determine the priority (High, Medium, Low) based on the urgency conveyed in the action text.
- Determine due_date_iso: Extract a due date if mentioned (e.g., 'by tomorrow', 'in 2 days'). Use the provided `anchor_date` (which represents when the action was requested) as the baseline to calculate relative times. Format it as an ISO 8601 string. If no deadline is implied, return null.
"""

    def generate_batch_task(self, actions_data: list[dict]) -> BatchExtractedTaskBlueprint | None:
        """
        Coordinates the LLM context evaluation to generate a batch of task blueprints from extracted actions.
        """
        if not actions_data:
            return None

        prompt = self._build_batch_generation_prompt(actions_data)
        
        try:
            # Call the generic engine and enforce strict pydantic output
            blueprint: BatchExtractedTaskBlueprint = self.llm.generate_structured_json(
                prompt=prompt, 
                response_schema=BatchExtractedTaskBlueprint
            )
            return blueprint
        except Exception as e:
            print(f"[TaskGenerationService] Failed to generate task blueprints: {e}")
            return None
