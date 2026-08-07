from typing import List, TypedDict, Optional, Dict, Any, Set
from datetime import datetime
from pydantic import BaseModel, Field

# =====================================================================
# TASK TAXONOMY CONSTANTS
# =====================================================================
# Task Status: 'pending' (active), 'completed' (resolved), 'dismissed' (closed without action)
VALID_TASK_STATUSES: Set[str] = {"pending", "completed", "dismissed"}

# Task Source: 'system' (extracted by Gemini AI worker), 'manual' (created by user)
VALID_TASK_SOURCES: Set[str] = {"system", "manual"}

# Task Priority: 'high', 'medium', 'low' (default: 'medium')
VALID_TASK_PRIORITIES: Set[str] = {"high", "medium", "low"}

# Task Intent Label: Categorizes action type
VALID_INTENT_LABELS: Set[str] = {
    "schedule_meeting",
    "reply_requested",
    "review_document",
    "provide_information",
    "make_payment",
    "follow_up",
    "other",
}

# =====================================================================
# 1. INTERNAL DATABASE & WORKER SCHEMAS (TypedDict - Zero Performance Cost)
# =====================================================================

class TaskRow(TypedDict):
    """
    Direct 1:1 mapping of Database Task record structure.
    """
    email_fact_id: Optional[str]  # UUID, null for manual tasks or ON DELETE SET NULL
    email_id: str  # UUID, required email reference
    thread_id: str  # UUID, required thread reference
    user_id: str  # UUID
    source: str  # 'system' (AI worker extracted) or 'manual' (user created)
    title: str
    status: str  # 'pending', 'completed', 'dismissed'
    priority: str  # 'high', 'medium', 'low'
    intent_label: str  # 'schedule_meeting', 'reply_requested', 'review_document', 'provide_information', 'make_payment', 'follow_up', 'other'
    action_fingerprint: str
    enriched_context: Dict[str, Any]  # JSONB mapping
    due_date: Optional[datetime]


class TaskUpdatePayload(TypedDict):
    """Payload passed internally to repositories to execute a task state transition."""
    id: str  # UUID
    status: str  # 'completed' or 'dismissed' (manually resolved by user)
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
    intent_label: str = Field(description=f"Categorize the action intent as one of the following: {', '.join(sorted(VALID_INTENT_LABELS))}.")
    priority: str = Field(description=f"Task urgency: {', '.join(sorted(VALID_TASK_PRIORITIES))}.")
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
    does_need_auto_draft: Optional[bool] = Field(
        None,
        description="True if the thread requires an AI-generated draft response for the user. Set to null if has_actionable_tasks is False."
    )