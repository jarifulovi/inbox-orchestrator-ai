from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.services.search.search_core_service import CoreSearchService


class SearchWebService:
    """
    Web Service adapter for Semantic Vector Search operations.
    Delegates dynamic threshold relaxation, RPC execution, and hard capping to CoreSearchService.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client
        self.core_search_service = CoreSearchService(db_client=db_client)

    async def smart_search(
        self,
        account_id: str,
        query: str,
        limit: int = 15,
        offset: int = 0,
        similarity_cutoff: float = 0.35
    ) -> List[Dict[str, Any]]:
        """Delegates smart vector search to CoreSearchService with hard capping."""
        return await self.core_search_service.smart_search(
            account_id=account_id,
            query=query,
            max_results=limit
        )
