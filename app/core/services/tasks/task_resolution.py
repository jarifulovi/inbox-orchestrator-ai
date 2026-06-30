from typing import List
from core.llm.client import LLMClient
from core.schemas.tasks import WorkerThreadContext, BatchThreadResolution, TaskUpdatePayload

class TaskResolutionService:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def _build_evaluation_prompt(self, context: WorkerThreadContext) -> str:
        """Constructs a clean, context-dense batch evaluation prompt."""
        tasks_section = ""
        for task in context["pending_tasks"]:
            tasks_section += f"- [Task ID: {task['id']}] Title: {task['title']}\n"

        emails_section = "\n".join(
            [f"--- Email Message ---\n{body}" for body in context["new_email_bodies"]]
        )

        return f"""
You are an advanced internal operations assistant evaluating task resolution states based on email thread updates.

Here are the active pending tasks assigned to this email thread:
{tasks_section}

Here are the new incoming email replies received on this thread:
{emails_section}

Your Goal:
Review the new email messages and determine if the user has completed or resolved the requirements for each individual Task ID. 
Only mark a task as completed (is_completed: true) if the emails explicitly show the action has been fulfilled, replied to, or concluded. Otherwise, leave it as false.
"""

    def evaluate_thread_resolution(self, context: WorkerThreadContext) -> List[TaskUpdatePayload]:
        """
        Coordinates the LLM context evaluation and packages the structural DB mutations.
        """
        if not context["pending_tasks"] or not context["new_email_bodies"]:
            return []

        prompt = self._build_evaluation_prompt(context)
        
        # Call the generic engine
        raw_resolution: BatchThreadResolution = self.llm.generate_structured_json(
            prompt=prompt, 
            response_schema=BatchThreadResolution
        )

        updates: List[TaskUpdatePayload] = []
        for eval_result in raw_resolution.task_evaluations:
            matching_task = next((t for t in context["pending_tasks"] if t["id"] == eval_result.id), None)
            if not matching_task:
                continue

            if eval_result.is_completed:
                updated_context = matching_task.get("enriched_context", {}).copy()
                updated_context["resolution_summary"] = eval_result.resolution_summary
                
                updates.append({
                    "id": eval_result.id,
                    "status": "completed",
                    "enriched_context": updated_context
                })

        return updates