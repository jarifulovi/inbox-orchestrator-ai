from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ThreadStatusUpdatePayload(BaseModel):
    workflow_status: str = Field(..., description="Target workflow status ('archived', 'unarchive', 'needs_action', etc.)")


class ThreadStatusUpdateResponse(BaseModel):
    status: str
    thread: Dict[str, Any]
    evaluated_status: Optional[str] = None
