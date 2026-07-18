from datetime import datetime
from typing import List, TypedDict, Optional, Dict, Any
from pydantic import BaseModel, Field

# =====================================================================
# 1. INTERNAL DATABASE & WORKER SCHEMAS (TypedDict - Zero Performance Cost)
# =====================================================================

class TaskRow(TypedDict):
    """
    Direct 1:1 mapping of your Database Task record structure.
    Used for type safety when extracting data via repositories.
    """
    extracted_action_id: str  # UUID
    email_id: str  # UUID
    thread_id: str  # UUID
    user_id: str  # UUID
    title: str
    status: str  # 'pending', 'completed', 'dismissed'
    priority: str  # 'High', 'Medium', 'Low'
    intent_label: str  # 'schedule_meeting', 'reply_requested', 'review_document', 'provide_information', 'make_payment', 'follow_up', 'other'
    action_fingerprint: str
    enriched_context: Dict[str, Any]  # JSONB mapping
    due_date: Optional[datetime]


class TaskUpdatePayload(TypedDict):
    """Payload passed internally to repositories to execute a task state transition."""
    id: str  # UUID
    status: str  # 'completed' or 'dismissed' (if resolved by worker)
    enriched_context: Dict[str, Any]  # To append resolution_summary or log details


class WorkerThreadContext(TypedDict):
    """
    The structural context extracted by the background runner.
    Groups identical fingerprints/threads for single-batch LLM evaluation.
    """
    thread_id: str
    pending_tasks: List[TaskRow]
    new_email_bodies: List[str]  # The incoming thread responses to evaluate against


# =====================================================================
# 2. LLM STRUCTURED OUTPUT SCHEMAS (Pydantic - Strict Gemini API Mapping)
# =====================================================================

class TaskResolution(BaseModel):
    """LLM representation of an individual task evaluation request."""
    id: str = Field(
        description="The unique task UUID string provided in the evaluation context."
    )
    status: str = Field(
        description="Determine the status of this task based on the emails: 'completed' (fully resolved or fulfilled), 'dismissed' (no longer relevant or explicitly cancelled), or 'pending' (still needs action)."
    )
    resolution_summary: str = Field(
        description="A clear, concise 1-2 sentence summary explaining why this task is completed or remains pending based on the email data."
    )


class BatchThreadResolution(BaseModel):
    """The strict blueprint passed to Gemini to evaluate all thread tasks at once."""
    task_evaluations: List[TaskResolution] = Field(
        description="List of resolution analysis records for each evaluated task ID."
    )


class ExtractedTaskBlueprint(BaseModel):
    """The core task details extracted by Gemini from an action."""
    extracted_action_id: str = Field(description="The UUID of the extracted action this task is generated for.")
    is_actionable_task: bool = Field(description="True if the extracted action represents a real, uncompleted task that a user needs to act on. False if it's informational, already done, or too vague.")
    title: str = Field(description="Actionable and clear title for the task.")
    intent_label: str = Field(description="Categorize the action intent as one of the following: 'schedule_meeting', 'reply_requested', 'review_document', 'provide_information', 'make_payment', 'follow_up', or 'other'.")
    priority: str = Field(description="Task urgency: 'High', 'Medium', or 'Low'.")
    due_date_iso: Optional[str] = Field(description="The ISO 8601 formatted due date for the task, if one can be determined. Use the provided anchor_date as the current/received date to calculate relative times (e.g. 'in 2 days').")

class BatchExtractedTaskBlueprint(BaseModel):
    """Batch response of extracted tasks."""
    tasks: List[ExtractedTaskBlueprint]


class UnifiedThreadOrchestrationResponse(BaseModel):
    """Unified Gemini response schema for thread-by-thread features orchestration."""
    task_generations: List[ExtractedTaskBlueprint] = Field(
        description="Task blueprints generated from pre-extracted action items on this thread."
    )
    thread_summary: str = Field(
        description="A concise, updated 2-3 sentence summary of the entire thread conversation."
    )
    thread_priority: str = Field(
        description="The overall derived priority of the thread ('High', 'Medium', 'Low') based on urgency of tasks and tone."
    )
    last_user_email_expects_reply: bool = Field(
        description="True if the last email sent by the user contains an action item, question, or request expecting a reply from the recipient. False if it is concluding (e.g. 'thanks') or doesn't expect a reply."
    )