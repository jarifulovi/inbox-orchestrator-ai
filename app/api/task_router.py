from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.web_services import TaskWebService
from app.api.deps.account import get_verified_account_id
from app.api.deps.auth import get_current_user
from app.core.db.supabase import get_supabase_client
from app.schemas.task_schemas import TaskCreatePayload, TaskUpdatePayload

router = APIRouter(prefix="/api/emails/tasks", tags=["tasks"])


@router.get("")
@router.get("/")
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


@router.post("")
@router.post("/")
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


@router.patch("/{task_id}")
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


@router.delete("/{task_id}")
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
