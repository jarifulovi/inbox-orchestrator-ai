from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from app.web_services.email_web_service import EmailWebService
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client
from app.api.deps.auth import get_current_user

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("/")
async def list_emails(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        classification: Optional[str] = None,
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = EmailWebService(db)
    emails = await service.get_user_emails(account_id, limit, offset, classification)
    return {"emails": emails}


@router.get("/threads")
async def list_threads(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = EmailWebService(db)
    threads = await service.get_user_threads(account_id, limit, offset)
    return {"threads": threads}


@router.post("/sync")
async def sync_inbox(
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = EmailWebService(db)
    await service.sync_user_inbox(account_id)
    return {"status": "success"}


@router.get("/search")
async def search_emails(
        q: str = Query(..., min_length=3, description="Search query"),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        similarity_cutoff: float = Query(0.35, ge=0.0, le=1.0),
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    if not q or len(q.strip()) < 3:
        return {"results": []}
    service = EmailWebService(db)
    results = await service.smart_search(
        account_id=account_id,
        query=q,
        limit=limit,
        offset=offset,
        similarity_cutoff=similarity_cutoff
    )
    return {"results": results}


@router.get("/tasks")
async def list_tasks(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        priority: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        intent_label: Optional[str] = Query(None),
        overdue: Optional[bool] = Query(None),
        source: Optional[str] = Query(None),
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = EmailWebService(db)
    result = await service.get_user_tasks(
        account_id=account_id,
        limit=limit,
        offset=offset,
        priority=priority,
        status=status,
        intent_label=intent_label,
        overdue=overdue,
        source=source
    )
    return result


@router.get("/{email_id}")
async def view_email(
        email_id: str,
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = EmailWebService(db)
    email = await service.get_email_details(email_id, account_id)

    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    return email




@router.post("/tasks/{task_id}/status")
async def update_task_status(
        task_id: str,
        payload: dict,
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
):
    status = payload.get("status")
    if status not in ("completed", "dismissed"):
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Only 'completed' or 'dismissed' are allowed for manual updates."
        )

    user_id = auth_user.get("id")

    # 1. Verify ownership: check that the task exists and belongs to the authenticated user
    try:
        task_res = db.table("tasks").select("id, user_id").eq("id", task_id).single().execute()
        task = task_res.data
    except Exception:
        task = None

    if not task:
        raise HTTPException(status_code=404, detail="Task not found or access denied")
    
    if task["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied. You do not own this task.")

    # 2. Update status in tasks table
    db.table("tasks").update({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", task_id).execute()

    return {"status": "success", "task_id": task_id, "new_status": status}