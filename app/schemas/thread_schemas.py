from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ThreadStatusUpdatePayload(BaseModel):
    workflow_status: str = Field(..., description="Target workflow status ('archived', 'unarchive', 'needs_action', etc.)")


class ThreadStatusUpdateResponse(BaseModel):
    status: str
    thread: Dict[str, Any]
    evaluated_status: Optional[str] = None


class UserThreadSummaryOutput(BaseModel):
    summary: str = Field(..., description="Concise 3-5 sentence summary of the email discussion, key points, and current state.")
    priority: Optional[str] = Field("medium", description="Priority level: 'high', 'medium', or 'low'.")
    key_takeaways: list[str] = Field(default_factory=list, description="2-3 bullet point key takeaways.")


class UserThreadSummaryResponse(BaseModel):
    status: str
    summary: str
    priority: str
    key_takeaways: list[str]
    summary_generated_at: str
    thread: Dict[str, Any]
