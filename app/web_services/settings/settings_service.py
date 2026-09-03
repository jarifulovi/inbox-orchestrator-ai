from typing import Dict, Any
from supabase import Client
from app.schemas.settings_schemas import UserSettingsPayload

DEFAULT_SETTINGS = {
    "enable_auto_task": True,
    "enable_auto_draft": False,
    "summary_format": "paragraph",
    "ai_model": "gemini-3.6-flash"
}


class SettingsWebService:
    def __init__(self, db_client: Client):
        self.db = db_client

    def get_user_settings(self, auth_user: dict) -> UserSettingsPayload:
        user_metadata = auth_user.get("user_metadata") or {}
        raw_settings = user_metadata.get("settings") or {}

        merged = {
            "enable_auto_task": raw_settings.get("enable_auto_task", DEFAULT_SETTINGS["enable_auto_task"]),
            "enable_auto_draft": raw_settings.get("enable_auto_draft", DEFAULT_SETTINGS["enable_auto_draft"]),
            "summary_format": raw_settings.get("summary_format", DEFAULT_SETTINGS["summary_format"]),
            "ai_model": raw_settings.get("ai_model", DEFAULT_SETTINGS["ai_model"]),
        }
        return UserSettingsPayload(**merged)

    def update_user_settings(self, auth_user: dict, new_settings: UserSettingsPayload) -> UserSettingsPayload:
        user_id = auth_user.get("id")
        user_metadata = auth_user.get("user_metadata") or {}

        updated_settings = new_settings.model_dump()
        user_metadata["settings"] = updated_settings

        try:
            self.db.auth.admin.update_user_by_id(user_id, {"user_metadata": user_metadata})
        except Exception as e:
            print(f"[SETTINGS WARNING] Auth admin metadata update fallback: {e}")

        return new_settings
