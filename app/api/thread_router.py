from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.web_services import ThreadWebService
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client
from app.schemas.thread_schemas import ThreadStatusUpdatePayload

router = APIRouter(prefix="/api/emails", tags=["threads"])


@router.get("/threads")
async def list_threads(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        workflow_status: Optional[str] = Query(None),
        priority: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        category: Optional[str] = Query(None),
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
        q=q,
        category=category
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


from app.api.deps.auth import get_current_user

@router.post("/threads/{thread_id}/summary")
async def generate_thread_summary(
        thread_id: str,
        force_refresh: bool = Query(False),
        account_id: str = Depends(get_verified_account_id),
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
):
    service = ThreadWebService(db)
    try:
        result = await service.generate_user_thread_summary(
            thread_id, 
            account_id, 
            auth_user=auth_user,
            force_refresh=force_refresh
        )
        return {"status": "success", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback
        print(f"[SUMMARY API ERROR] Summary generation failed for thread {thread_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {str(e)}")
