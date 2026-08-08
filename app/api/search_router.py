from fastapi import APIRouter, Depends, Query
from app.web_services import SearchWebService
from app.api.deps.account import get_verified_account_id
from app.core.db.supabase import get_supabase_client

router = APIRouter(prefix="/api/emails/search", tags=["search"])


@router.get("")
@router.get("/")
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
