from pydantic import BaseModel, Field
from typing import Optional


class UserSettingsPayload(BaseModel):
    enable_auto_task: bool = Field(True, description="Enable automatic task extraction during thread orchestration")
    enable_auto_draft: bool = Field(False, description="Enable background auto-draft creation for actionable threads")
    summary_format: str = Field("paragraph", description="Summary format ('paragraph', 'bullets', 'concise')")
    ai_model: str = Field("gemini-3.5-flash", description="Language model ('gemini-3.5-flash', 'gemini-3.5-pro')")


class UserSettingsResponse(BaseModel):
    status: str
    settings: UserSettingsPayload
