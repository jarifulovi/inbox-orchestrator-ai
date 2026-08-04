from typing import Optional
from pydantic import BaseModel, Field


class TaskCreatePayload(BaseModel):
    """Payload for manual task creation."""
    title: str = Field(..., description="Actionable title for the manual task.")
    email_id: str = Field(..., description="The target email UUID linked to this task.")
    account_id: Optional[str] = Field(None, description="Optional connected account ID.")
    thread_id: Optional[str] = Field(None, description="Optional thread UUID linked to this task. Derived from email if omitted.")
    priority: Optional[str] = Field("medium", description="Task priority: 'high', 'medium', or 'low'. Defaults to 'medium'.")
    intent_label: Optional[str] = Field("other", description="Task intent label (e.g., 'schedule_meeting', 'reply_requested', 'review_document', 'provide_information', 'make_payment', 'follow_up', 'other'). Defaults to 'other'.")
    due_date: Optional[str] = Field(None, description="ISO 8601 formatted due date string (or None).")


class TaskUpdatePayload(BaseModel):
    """Payload for partial updates to an existing task (system or manual)."""
    title: Optional[str] = Field(None, description="Updated title for the task.")
    status: Optional[str] = Field(None, description="Updated workflow state: 'pending', 'completed', or 'dismissed'.")
    priority: Optional[str] = Field(None, description="Updated task priority: 'high', 'medium', or 'low'.")
    intent_label: Optional[str] = Field(None, description="Updated intent classification label.")
    due_date: Optional[str] = Field(None, description="Updated ISO 8601 formatted due date string (or None).")
