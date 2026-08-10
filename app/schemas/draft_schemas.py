from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class CreateDraftRequest(BaseModel):
    recipient_to: List[str] = Field(..., description="Array of recipient email addresses")
    subject: Optional[str] = Field(None, description="Draft subject line")
    body: Optional[str] = Field(None, description="Draft content text/markdown")
    reply_to_email_id: Optional[str] = Field(None, description="UUID of parent email being replied to")
    resolved_task_ids: Optional[List[str]] = Field(default_factory=list, description="Array of task UUIDs to mark as completed")
    generation_context: Optional[Dict[str, Any]] = Field(None, description="AI context parameters and prompt metadata")


class UpdateDraftRequest(BaseModel):
    recipient_to: Optional[List[str]] = Field(None, description="Updated array of recipient email addresses")
    subject: Optional[str] = Field(None, description="Updated draft subject line")
    body: Optional[str] = Field(None, description="Updated draft content text/markdown")
    resolved_task_ids: Optional[List[str]] = Field(None, description="Updated array of task UUIDs to mark as completed")


class DraftResponseData(BaseModel):
    id: str
    thread_id: str
    reply_to_email_id: Optional[str] = None
    user_id: str
    connected_account_id: str
    recipient_to: List[str]
    subject: Optional[str] = None
    body: Optional[str] = None
    status: str
    gmail_draft_id: Optional[str] = None
    generation_context: Optional[Dict[str, Any]] = None
    error_log: Optional[str] = None
    resolved_task_ids: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class DraftApiResponse(BaseModel):
    status: str
    data: DraftResponseData
