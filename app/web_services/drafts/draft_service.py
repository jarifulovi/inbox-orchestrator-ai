from typing import List, Dict, Any
from app.core.services.drafts.draft_core_service import CoreDraftService
from app.schemas.draft_schemas import CreateDraftRequest, UpdateDraftRequest


class DraftWebService:
    """
    Web Service adapter handling FastAPI endpoint payloads, delegating core draft operations,
    database persistence, task resolutions, and Gmail API sync to CoreDraftService.
    """

    def __init__(self, db_client):
        self.db = db_client
        self.core_draft_service = CoreDraftService(db_client)

    async def create_manual_draft(
        self,
        user_id: str,
        account_id: str,
        thread_id: str,
        payload: CreateDraftRequest
    ) -> Dict[str, Any]:
        """Validates CreateDraftRequest payload and delegates draft creation to CoreDraftService."""
        return await self.core_draft_service.create_draft(
            user_id=user_id,
            account_id=account_id,
            thread_id=thread_id,
            recipient_to=payload.recipient_to,
            subject=payload.subject,
            body=payload.body,
            reply_to_email_id=payload.reply_to_email_id,
            resolved_task_ids=payload.resolved_task_ids,
            generation_context=payload.generation_context,
            status="draft"
        )

    async def get_thread_drafts(self, user_id: str, account_id: str, thread_id: str) -> List[Dict[str, Any]]:
        """Delegates fetching thread drafts to CoreDraftService."""
        return await self.core_draft_service.get_thread_drafts(
            user_id=user_id,
            account_id=account_id,
            thread_id=thread_id
        )

    async def get_account_drafts(self, user_id: str, account_id: str, status_filter: str = "all") -> List[Dict[str, Any]]:
        """Delegates fetching account-wide drafts with optional status filter to CoreDraftService."""
        return await self.core_draft_service.get_account_drafts(
            user_id=user_id,
            account_id=account_id,
            status_filter=status_filter
        )

    async def update_manual_draft(
        self,
        user_id: str,
        account_id: str,
        draft_id: str,
        payload: UpdateDraftRequest
    ) -> Dict[str, Any]:
        """Validates UpdateDraftRequest payload and delegates draft update to CoreDraftService."""
        return await self.core_draft_service.update_draft(
            user_id=user_id,
            account_id=account_id,
            draft_id=draft_id,
            recipient_to=payload.recipient_to,
            subject=payload.subject,
            body=payload.body,
            resolved_task_ids=payload.resolved_task_ids
        )

    async def send_draft(self, user_id: str, account_id: str, draft_id: str) -> Dict[str, Any]:
        """Delegates sending draft via Gmail API to CoreDraftService."""
        return await self.core_draft_service.send_draft(
            user_id=user_id,
            account_id=account_id,
            draft_id=draft_id
        )

    async def generate_ai_draft(
        self,
        user_id: str,
        account_id: str,
        thread_id: str,
        payload
    ) -> Dict[str, Any]:
        """Delegates manual AI draft reply content generation to CoreDraftService."""
        return await self.core_draft_service.generate_ai_draft_content(
            user_id=user_id,
            account_id=account_id,
            thread_id=thread_id,
            ai_instructions=payload.ai_instructions,
            tone=payload.tone or "Professional",
            resolved_task_ids=payload.resolved_task_ids
        )
