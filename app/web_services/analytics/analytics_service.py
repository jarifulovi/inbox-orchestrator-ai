from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.services.analytics.sender_analytics_core_service import SenderAnalyticsCoreService


class AnalyticsWebService:
    """
    Web Service adapter for Analytics and Workspace Intelligence operations.
    Delegates sender metrics aggregation and system performance queries to SenderAnalyticsCoreService.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client
        self.core_analytics_service = SenderAnalyticsCoreService(db_client=db_client)

    async def get_sender_analytics(
        self,
        account_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Delegates sender analytics retrieval to Core Domain Service."""
        return await self.core_analytics_service.get_sender_analytics(
            account_id=account_id,
            limit=limit
        )

    async def get_system_analytics(self, account_id: str) -> Dict[str, Any]:
        """Delegates system performance analytics retrieval to Core Domain Service."""
        return await self.core_analytics_service.get_system_analytics(
            account_id=account_id
        )
