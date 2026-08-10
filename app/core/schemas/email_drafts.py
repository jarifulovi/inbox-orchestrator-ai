from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class EmailDraftRow(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    thread_id: UUID
    reply_to_email_id: Optional[UUID] = None
    user_id: UUID
    connected_account_id: UUID
    recipient_to: List[str]
    subject: Optional[str] = None
    body: Optional[str] = None
    # Statuses: 'draft', 'pending_approval', 'sent', 'failed'
    status: str = "draft"
    generation_context: Optional[Dict[str, Any]] = None
    gmail_draft_id: Optional[str] = None
    error_log: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EmailDraftResolutionRow(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    email_draft_id: UUID
    task_id: UUID
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))