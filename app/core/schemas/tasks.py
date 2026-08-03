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
    email_fact_id: Optional[str]  # UUID, null for manual tasks or ON DELETE SET NULL
    email_id: str  # UUID, required email reference
    thread_id: str  # UUID, required thread reference
    user_id: str  # UUID
    source: str  # 'system' (default) or 'manual'
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


class ExtractedTaskBlueprint(BaseModel):
    """The core task details extracted by Gemini from an action fact."""
    email_fact_id: str = Field(description="The UUID of the email fact this task is generated for.")
    is_actionable_task: bool = Field(description="True if the email fact represents a real, uncompleted task that a user needs to act on. False if it's informational, already done, or too vague.")
    title: str = Field(description="Actionable and clear title for the task.")
    intent_label: str = Field(description="Categorize the action intent as one of the following: 'schedule_meeting', 'reply_requested', 'review_document', 'provide_information', 'make_payment', 'follow_up', or 'other'.")
    priority: str = Field(description="Task urgency: 'High', 'Medium', or 'Low'.")
    due_date_iso: Optional[str] = Field(description="The ISO 8601 formatted due date for the task, if one can be determined. Use the provided anchor_date as the current/received date to calculate relative times (e.g. 'in 2 days').")

class BatchExtractedTaskBlueprint(BaseModel):
    """Batch response of extracted tasks."""
    tasks: List[ExtractedTaskBlueprint]


class UnifiedThreadOrchestrationResponse(BaseModel):
    """Unified Gemini response schema for thread-by-thread features orchestration."""
    has_actionable_tasks: bool = Field(
        description="True if there is at least one new concrete task requiring user action. False if purely informational, news, subscriptions, generic status updates, closures, or noise."
    )
    task_generations: List[ExtractedTaskBlueprint] = Field(
        default=[],
        description="Task blueprints generated from pre-extracted facts. Empty list if has_actionable_tasks is False."
    )
    thread_summary: Optional[str] = Field(
        None,
        description="Concise 2-3 sentence thread summary. Set to null if has_actionable_tasks is False."
    )
    thread_priority: Optional[str] = Field(
        None,
        description="Overall thread priority ('High', 'Medium', 'Low'). Set to null if has_actionable_tasks is False."
    )
    last_user_email_expects_reply: Optional[bool] = Field(
        None,
        description="True if the last user email expects a response. Set to null if has_actionable_tasks is False."
    )