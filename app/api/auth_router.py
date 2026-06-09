from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.api.deps.auth import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.auth_schemas import MeResponseSchema, GoogleAuthUrlResponse, GoogleCallbackResponse
from app.web_services.auth_web_service import AuthWebService

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=MeResponseSchema)
async def get_me(
    db: Client = Depends(get_supabase_client),
    auth_user: dict = Depends(get_current_user)
):
    """
    Returns current authenticated user and connected account state.
    """
    service = AuthWebService(db_client=db)
    return await service.get_me(auth_user)



@router.get("/google/connect", response_model=GoogleAuthUrlResponse)
async def connect_google_account(
    auth_user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase_client)
):
    service = AuthWebService(db_client=db)
    return await service.generate_google_auth_url(auth_user=auth_user)


@router.get("/google/callback", response_model=GoogleCallbackResponse)
async def google_callback(
    code: str,
    state: str,
    db: Client = Depends(get_supabase_client)
):
    service = AuthWebService(db_client=db)
    return await service.handle_google_callback(
        code=code,
        state=state
    )