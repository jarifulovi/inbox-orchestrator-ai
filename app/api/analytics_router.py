from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any
from app.web_services import AnalyticsWebService
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/senders")
async def get_sender_analytics(
    limit: int = Query(50, ge=1, le=200, description="Max senders to return"),
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
) -> Dict[str, Any]:
    """Retrieves sender analytics and workload metrics for connected email account."""
    service = AnalyticsWebService(db)
    results = await service.get_sender_analytics(account_id=account_id, limit=limit)
    return {"results": results}


@router.get("/system")
async def get_system_analytics(
    account_id: str = Depends(get_verified_account_id),
    db=Depends(get_supabase_client)
) -> Dict[str, Any]:
    """Retrieves system performance metrics for connected email account."""
    service = AnalyticsWebService(db)
    summary = await service.get_system_analytics(account_id=account_id)
    return {"summary": summary}
