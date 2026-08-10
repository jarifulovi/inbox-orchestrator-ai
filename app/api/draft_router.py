from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.api.deps.account import get_verified_account_id
from app.api.deps.auth import get_current_user
from app.core.db.supabase import get_supabase_client
from app.schemas.draft_schemas import CreateDraftRequest, UpdateDraftRequest, DraftApiResponse
from app.web_services.drafts.draft_service import DraftWebService

router = APIRouter(prefix="/api/emails", tags=["drafts"])


@router.post("/threads/{thread_id}/drafts", response_model=DraftApiResponse)
async def create_thread_draft(
    thread_id: str,
    payload: CreateDraftRequest,
    current_user=Depends(get_current_user),
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
):
    """
    Creates a manual email draft for a thread, synchronizes with Gmail API (users().drafts().create),
    persists into public.email_drafts, and resolves selected pending task IDs via public.email_draft_resolutions.
    """
    print(f"[DRAFT API INFO] Initiating manual draft creation for thread_id={thread_id}, account_id={account_id}")
    service = DraftWebService(db)
    try:
        draft = await service.create_manual_draft(
            user_id=current_user["id"],
            account_id=account_id,
            thread_id=thread_id,
            payload=payload
        )
        print(f"[DRAFT API SUCCESS] Draft created successfully with id={draft.get('id')}, gmail_draft_id={draft.get('gmail_draft_id')}")
        return {"status": "success", "data": draft}
    except KeyError as e:
        print(f"[DRAFT API NOT FOUND] {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        print(f"[DRAFT API BAD REQUEST] {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        print(f"[DRAFT API ERROR] Manual draft creation failed for thread {thread_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Draft creation failed: {str(e)}")


@router.get("/threads/{thread_id}/drafts")
async def list_thread_drafts(
    thread_id: str,
    current_user=Depends(get_current_user),
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
):
    """Fetches all existing draft records for a thread."""
    service = DraftWebService(db)
    try:
        drafts = await service.get_thread_drafts(
            user_id=current_user["id"],
            account_id=account_id,
            thread_id=thread_id
        )
        return {"status": "success", "data": drafts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch drafts: {str(e)}")


@router.put("/drafts/{draft_id}", response_model=DraftApiResponse)
async def update_draft(
    draft_id: str,
    payload: UpdateDraftRequest,
    current_user=Depends(get_current_user),
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
):
    """Updates draft text/recipients in DB and syncs changes to Gmail API (users().drafts().update)."""
    service = DraftWebService(db)
    try:
        draft = await service.update_manual_draft(
            user_id=current_user["id"],
            account_id=account_id,
            draft_id=draft_id,
            payload=payload
        )
        return {"status": "success", "data": draft}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Draft update failed: {str(e)}")


@router.post("/drafts/{draft_id}/send", response_model=DraftApiResponse)
async def send_draft(
    draft_id: str,
    current_user=Depends(get_current_user),
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
):
    """Sends draft via Gmail API (users().drafts().send) and marks status = 'sent'."""
    service = DraftWebService(db)
    try:
        draft = await service.send_draft(
            user_id=current_user["id"],
            account_id=account_id,
            draft_id=draft_id
        )
        return {"status": "success", "data": draft}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Draft sending failed: {str(e)}")
