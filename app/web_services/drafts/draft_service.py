import base64
import uuid
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.core.services.auth_service import CoreAuthService
from app.schemas.draft_schemas import CreateDraftRequest, UpdateDraftRequest, DraftResponseData


class DraftWebService:
    """
    Web Service handling manual draft creation, database persistence, task auto-resolutions,
    and bi-directional synchronization with Google Gmail API (users().drafts).
    """

    def __init__(self, db_client):
        self.db = db_client
        self.core_auth = CoreAuthService()

    async def create_manual_draft(
        self,
        user_id: str,
        account_id: str,
        thread_id: str,
        payload: CreateDraftRequest
    ) -> Dict[str, Any]:
        """
        Creates a manual draft, synchronizes with Gmail API (users().drafts().create),
        persists into public.email_drafts, and resolves selected pending tasks via public.email_draft_resolutions.
        """
        # 1. Verify thread ownership
        thread_res = self.db.table("email_threads") \
            .select("id, thread_id, subject, connected_account_id, user_id") \
            .eq("id", thread_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not thread_res.data:
            raise KeyError(f"Thread {thread_id} not found or access denied for account {account_id}.")

        thread = thread_res.data
        gmail_thread_id = thread.get("thread_id")

        # 2. Fetch reply-to email headers if reply_to_email_id is provided
        reply_to_msg_id = None
        if payload.reply_to_email_id:
            email_res = self.db.table("emails") \
                .select("id, message_id") \
                .eq("id", payload.reply_to_email_id) \
                .single() \
                .execute()
            if email_res.data:
                reply_to_msg_id = email_res.data.get("message_id")

        # 3. Obtain active Gmail SDK client with silent token rotation
        gmail_client = await self.core_auth.get_valid_credentials(account_id)

        # 4. Construct base64url MIME email message
        mime_msg = EmailMessage()
        mime_msg["To"] = ", ".join(payload.recipient_to)
        mime_msg["Subject"] = payload.subject or thread.get("subject") or ""
        if reply_to_msg_id:
            mime_msg["In-Reply-To"] = reply_to_msg_id
            mime_msg["References"] = reply_to_msg_id

        mime_msg.set_content(payload.body or "")

        raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
        draft_payload = {
            "message": {
                "raw": raw_bytes
            }
        }
        if gmail_thread_id:
            draft_payload["message"]["threadId"] = gmail_thread_id

        # 5. Execute Gmail API draft creation
        gmail_draft_id = None
        error_log = None
        try:
            gmail_res = gmail_client.users().drafts().create(userId="me", body=draft_payload).execute()
            gmail_draft_id = gmail_res.get("id")
        except Exception as e:
            error_log = f"Gmail draft sync failed: {str(e)}"
            print(f"[DRAFT WARNING] {error_log}")

        # 6. Insert record into public.email_drafts
        now_iso = datetime.now(timezone.utc).isoformat()
        draft_record_id = str(uuid.uuid4())

        draft_data = {
            "id": draft_record_id,
            "thread_id": thread_id,
            "reply_to_email_id": payload.reply_to_email_id,
            "user_id": user_id,
            "connected_account_id": account_id,
            "recipient_to": payload.recipient_to,
            "subject": payload.subject,
            "body": payload.body,
            "status": "draft",
            "generation_context": payload.generation_context,
            "gmail_draft_id": gmail_draft_id,
            "error_log": error_log,
            "created_at": now_iso,
            "updated_at": now_iso
        }

        self.db.table("email_drafts").insert(draft_data).execute()

        # 7. Process Task Resolutions (public.email_draft_resolutions & public.tasks)
        resolved_task_ids = payload.resolved_task_ids or []
        if resolved_task_ids:
            resolutions_to_insert = [
                {
                    "id": str(uuid.uuid4()),
                    "email_draft_id": draft_record_id,
                    "task_id": tid,
                    "resolved_at": now_iso
                }
                for tid in resolved_task_ids
            ]
            try:
                self.db.table("email_draft_resolutions").insert(resolutions_to_insert).execute()
                # Update task statuses to completed
                self.db.table("tasks") \
                    .update({"status": "completed", "updated_at": now_iso}) \
                    .in_("id", resolved_task_ids) \
                    .execute()
            except Exception as ex:
                print(f"[DRAFT RESOLUTIONS WARNING] Failed to persist task resolutions: {ex}")

        # Return formatted DraftResponseData dict
        draft_data["resolved_task_ids"] = resolved_task_ids
        return draft_data

    async def get_thread_drafts(self, user_id: str, account_id: str, thread_id: str) -> List[Dict[str, Any]]:
        """Fetches all existing draft records for a thread."""
        drafts_res = self.db.table("email_drafts") \
            .select("*") \
            .eq("thread_id", thread_id) \
            .eq("connected_account_id", account_id) \
            .order("created_at", desc=True) \
            .execute()

        drafts = drafts_res.data or []
        if not drafts:
            return []

        draft_ids = [d["id"] for d in drafts]
        resolutions_res = self.db.table("email_draft_resolutions") \
            .select("email_draft_id, task_id") \
            .in_("email_draft_id", draft_ids) \
            .execute()

        resolutions_by_draft: Dict[str, List[str]] = {}
        for r in (resolutions_res.data or []):
            resolutions_by_draft.setdefault(r["email_draft_id"], []).append(r["task_id"])

        for d in drafts:
            d["resolved_task_ids"] = resolutions_by_draft.get(d["id"], [])

        return drafts

    async def update_manual_draft(
        self,
        user_id: str,
        account_id: str,
        draft_id: str,
        payload: UpdateDraftRequest
    ) -> Dict[str, Any]:
        """Updates draft fields in public.email_drafts and syncs to Gmail via users().drafts().update."""
        draft_res = self.db.table("email_drafts") \
            .select("*") \
            .eq("id", draft_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not draft_res.data:
            raise KeyError(f"Draft {draft_id} not found or access denied.")

        draft = draft_res.data
        gmail_draft_id = draft.get("gmail_draft_id")

        now_iso = datetime.now(timezone.utc).isoformat()
        update_fields: Dict[str, Any] = {"updated_at": now_iso}

        if payload.recipient_to is not None:
            update_fields["recipient_to"] = payload.recipient_to
        if payload.subject is not None:
            update_fields["subject"] = payload.subject
        if payload.body is not None:
            update_fields["body"] = payload.body

        # Sync update to Gmail API if gmail_draft_id exists
        if gmail_draft_id:
            try:
                gmail_client = await self.core_auth.get_valid_credentials(account_id)
                new_recipients = payload.recipient_to if payload.recipient_to is not None else draft.get("recipient_to", [])
                new_subject = payload.subject if payload.subject is not None else draft.get("subject", "")
                new_body = payload.body if payload.body is not None else draft.get("body", "")

                mime_msg = EmailMessage()
                mime_msg["To"] = ", ".join(new_recipients)
                mime_msg["Subject"] = new_subject
                mime_msg.set_content(new_body)

                raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
                gmail_client.users().drafts().update(
                    userId="me",
                    id=gmail_draft_id,
                    body={"message": {"raw": raw_bytes}}
                ).execute()
            except Exception as e:
                print(f"[DRAFT UPDATE WARNING] Gmail draft update failed: {e}")

        # Update Supabase record
        self.db.table("email_drafts").update(update_fields).eq("id", draft_id).execute()

        # Handle task resolutions update if provided
        if payload.resolved_task_ids is not None:
            new_task_ids = payload.resolved_task_ids
            # Remove old draft resolutions
            self.db.table("email_draft_resolutions").delete().eq("email_draft_id", draft_id).execute()
            if new_task_ids:
                resolutions_to_insert = [
                    {
                        "id": str(uuid.uuid4()),
                        "email_draft_id": draft_id,
                        "task_id": tid,
                        "resolved_at": now_iso
                    }
                    for tid in new_task_ids
                ]
                self.db.table("email_draft_resolutions").insert(resolutions_to_insert).execute()
                self.db.table("tasks").update({"status": "completed", "updated_at": now_iso}).in_("id", new_task_ids).execute()

        # Re-fetch updated draft
        refreshed = self.db.table("email_drafts").select("*").eq("id", draft_id).single().execute()
        refreshed_data = refreshed.data
        refreshed_data["resolved_task_ids"] = payload.resolved_task_ids if payload.resolved_task_ids is not None else []
        return refreshed_data

    async def send_draft(self, user_id: str, account_id: str, draft_id: str) -> Dict[str, Any]:
        """Sends the draft via Gmail API (users().drafts().send) and marks status = 'sent'."""
        draft_res = self.db.table("email_drafts") \
            .select("*") \
            .eq("id", draft_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not draft_res.data:
            raise KeyError(f"Draft {draft_id} not found or access denied.")

        draft = draft_res.data
        gmail_draft_id = draft.get("gmail_draft_id")

        if gmail_draft_id:
            try:
                gmail_client = await self.core_auth.get_valid_credentials(account_id)
                gmail_client.users().drafts().send(userId="me", body={"id": gmail_draft_id}).execute()
            except Exception as e:
                print(f"[DRAFT SEND WARNING] Gmail draft send failed: {e}")

        now_iso = datetime.now(timezone.utc).isoformat()
        self.db.table("email_drafts").update({"status": "sent", "updated_at": now_iso}).eq("id", draft_id).execute()

        refreshed = self.db.table("email_drafts").select("*").eq("id", draft_id).single().execute()
        return refreshed.data
