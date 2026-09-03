from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.api.deps.auth import get_current_user
from app.core.db.supabase import get_supabase_client
from app.schemas.settings_schemas import UserSettingsPayload, UserSettingsResponse
from app.web_services.settings.settings_service import SettingsWebService

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    auth_user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase_client)
):
    service = SettingsWebService(db_client=db)
    settings = service.get_user_settings(auth_user)
    return {"status": "success", "settings": settings}


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    payload: UserSettingsPayload,
    auth_user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase_client)
):
    service = SettingsWebService(db_client=db)
    updated = service.update_user_settings(auth_user, payload)
    return {"status": "success", "settings": updated}
