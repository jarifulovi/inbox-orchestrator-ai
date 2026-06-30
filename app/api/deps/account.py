from fastapi import Depends, HTTPException, Query
from app.api.deps.auth import get_current_user
from app.core.db.supabase import get_supabase_client


async def get_verified_account_id(
        account_id: str = Query(..., description="The specific connected account ID being accessed"),
        auth_user: dict = Depends(get_current_user),
        db=Depends(get_supabase_client)
) -> str:
    """
    Validates that the requested account_id belongs to the authenticated user.
    Uncaught database issues bubble up directly to the global exception handler.
    """
    user_id = auth_user.get("id")

    # Verify ownership: check that the account_id matches the authenticated user_id
    res = db.table("connected_accounts").select("id").eq("id", account_id).eq("user_id", user_id).single().execute()

    if not res.data:
        raise HTTPException(
            status_code=403,
            detail="Access denied or account profile does not exist"
        )

    return res.data["id"]