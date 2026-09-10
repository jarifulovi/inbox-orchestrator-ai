from pydantic import BaseModel, Field
from typing import Optional


class UserSettingsPayload(BaseModel):
    enable_auto_task: bool = Field(True, description="Enable automatic task extraction during thread orchestration")
    enable_auto_draft: bool = Field(False, description="Enable background auto-draft creation for actionable threads")
    summary_format: str = Field("paragraph", description="Summary format ('paragraph', 'bullets', 'concise')")
    ai_model: int = Field(2, description="Language model index (1: gemini-3.5-flash-lite, 2: gemini-3.6-flash)")


class UserSettingsResponse(BaseModel):
    status: str
    settings: UserSettingsPayload
