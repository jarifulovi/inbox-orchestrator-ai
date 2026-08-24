from fastapi import APIRouter, Depends, HTTPException
from app.web_services.providers.google_calendar_service import GoogleCalendarWebService
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client

router = APIRouter(prefix="/api/emails", tags=["calendar"])


@router.post("/tasks/{task_id}/gcal-sync")
async def sync_task_to_google_calendar(
    task_id: str,
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
):
    service = GoogleCalendarWebService(db)
    try:
        res = await service.sync_task_to_gcal(task_id, account_id)
        return res
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Calendar sync failed: {str(e)}")
