from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.web_services import EmailWebService, GmailProviderService
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("")
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


from pydantic import BaseModel

class UnsubscribeRequest(BaseModel):
    sender_email: str

@router.post("/senders/unsubscribe")
async def unsubscribe_sender(
        payload: UnsubscribeRequest,
        account_id: str = Depends(get_verified_account_id),
        db=Depends(get_supabase_client)
):
    """Triggers One-Click Unsubscribe (RFC 8058) or Gmail Spam Filter fallback for a sender at provider level."""
    if not payload.sender_email or not payload.sender_email.strip():
        raise HTTPException(status_code=400, detail="sender_email is required.")

    service = GmailProviderService(db)
    result = await service.unsubscribe_sender(account_id=account_id, sender_email=payload.sender_email)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to unsubscribe sender."))

    return result