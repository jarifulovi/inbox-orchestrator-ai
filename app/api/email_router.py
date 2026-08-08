from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, HTTPException
from app.web_services import (
    EmailWebService,
    ThreadWebService,
    SearchWebService,
    TaskWebService,
)
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client
from app.api.deps.auth import get_current_user
from app.schemas.task_schemas import TaskCreatePayload, TaskUpdatePayload
from app.schemas.thread_schemas import ThreadStatusUpdatePayload, ThreadStatusUpdateResponse

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("/")
async def list_emails(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        q: Optional[str] = Query(None, description="Search query"),
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = EmailWebService(db)
    emails = await service.get_user_emails(account_id, limit, offset, q)
    return {"emails": emails}


@router.get("/threads")
async def list_threads(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        workflow_status: Optional[str] = Query(None),
        priority: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = ThreadWebService(db)
    threads = await service.get_user_threads(
        account_id=account_id,
        limit=limit,
        offset=offset,
        workflow_status=workflow_status,
        priority=priority,
        q=q
    )
    return {"threads": threads}


@router.get("/threads/{thread_id}")
async def get_thread_details(
        thread_id: str,
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = ThreadWebService(db)
    try:
        details = await service.get_thread_details(thread_id, account_id)
        return details
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found.")


@router.patch("/threads/{thread_id}/status")
async def update_thread_status(
        thread_id: str,
        payload: ThreadStatusUpdatePayload,
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = ThreadWebService(db)
    try:
        updated = await service.update_thread_status(thread_id, account_id, payload.workflow_status)
        return {"status": "success", "thread": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sync")
async def sync_inbox(
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    service = ThreadWebService(db)
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
    service = SearchWebService(db)
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
        email_id: Optional[str] = Query(None),
        account_id: str = Depends(get_verified_account_id),
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
):
    service = TaskWebService(db)
    user_id = auth_user.get("id")
    result = await service.get_user_tasks(
        user_id=user_id,
        account_id=account_id,
        limit=limit,
        offset=offset,
        priority=priority,
        status=status,
        intent_label=intent_label,
        overdue=overdue,
        source=source,
        email_id=email_id
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


@router.post("/tasks")
async def create_task(
        payload: TaskCreatePayload,
        account_id: Optional[str] = Query(None, description="Connected account ID"),
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
):
    service = TaskWebService(db)
    user_id = auth_user.get("id")
    target_account_id = account_id or payload.account_id

    if target_account_id:
        acc_res = db.table("connected_accounts").select("id").eq("id", target_account_id).eq("user_id", user_id).execute()
        if not acc_res.data:
            raise HTTPException(status_code=403, detail="Access denied or connected account does not belong to user")

    try:
        task = await service.create_manual_task(
            user_id=user_id,
            account_id=target_account_id,
            title=payload.title,
            email_id=payload.email_id,
            thread_id=payload.thread_id,
            priority=payload.priority,
            intent_label=payload.intent_label,
            due_date=payload.due_date
        )
        return task
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e).strip("'\""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e).strip("'\""))


@router.patch("/tasks/{task_id}")
async def update_task(
        task_id: str,
        payload: TaskUpdatePayload,
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
):
    service = TaskWebService(db)
    user_id = auth_user.get("id")
    try:
        updated_task = await service.update_user_task(
            task_id=task_id,
            user_id=user_id,
            title=payload.title,
            status=payload.status,
            priority=payload.priority,
            intent_label=payload.intent_label,
            due_date=payload.due_date
        )
        return updated_task
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task(
        task_id: str,
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
):
    service = TaskWebService(db)
    user_id = auth_user.get("id")
    try:
        res = await service.delete_user_task(task_id=task_id, user_id=user_id)
        return res
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))