import base64
import uuid
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.core.services.auth_service import ConnectedAccountService
from app.schemas.draft_schemas import CreateDraftRequest, UpdateDraftRequest, DraftResponseData
from app.web_services.tasks.thread_workflow_synchronizer import ThreadWorkflowSynchronizer


class DraftWebService:
    """
    Web Service handling manual draft creation, database persistence, task auto-resolutions,
    thread workflow status synchronization, and bi-directional synchronization with Google Gmail API.
    """

    def __init__(self, db_client):
        self.db = db_client
        self.core_auth = ConnectedAccountService(db_client=db_client)
        self.synchronizer = ThreadWorkflowSynchronizer(db_client)

    async def create_manual_draft(
        self,
        user_id: str,
        account_id: str,
        thread_id: str,
        payload: CreateDraftRequest
    ) -> Dict[str, Any]:
        """
        Creates a manual draft, synchronizes with Gmail API (users().drafts().create),
        persists into public.email_drafts, resolves selected pending tasks via public.email_draft_resolutions,
        and synchronizes thread workflow_status.
        """
        print(f"[DRAFT SERVICE LOG 1/6] Validating thread {thread_id} for account {account_id}")
        # 1. Verify thread ownership
        thread_res = self.db.table("email_threads") \
            .select("id, gmail_thread_id, subject, connected_account_id") \
            .eq("id", thread_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not thread_res.data:
            raise KeyError(f"Thread {thread_id} not found or access denied for account {account_id}.")

        thread = thread_res.data
        gmail_thread_id = thread.get("gmail_thread_id")
        print(f"[DRAFT SERVICE LOG 2/6] Found thread record. Gmail Thread ID: {gmail_thread_id}")

        # Check if an active un-sent draft already exists for this thread
        existing_draft_res = self.db.table("email_drafts") \
            .select("id") \
            .eq("thread_id", thread_id) \
            .eq("connected_account_id", account_id) \
            .in_("status", ["draft", "pending_approval"]) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if existing_draft_res.data:
            existing_draft_id = existing_draft_res.data[0]["id"]
            print(f"[DRAFT SERVICE UPSERT] Active draft {existing_draft_id} exists for thread. Updating existing draft...")
            update_payload = UpdateDraftRequest(
                recipient_to=payload.recipient_to,
                subject=payload.subject,
                body=payload.body,
                resolved_task_ids=payload.resolved_task_ids
            )
            return await self.update_manual_draft(
                user_id=user_id,
                account_id=account_id,
                draft_id=existing_draft_id,
                payload=update_payload
            )

        # 2. Fetch reply-to email headers if reply_to_email_id is provided
        reply_to_msg_id = None
        if payload.reply_to_email_id:
            email_res = self.db.table("emails") \
                .select("id, gmail_message_id") \
                .eq("id", payload.reply_to_email_id) \
                .single() \
                .execute()
            if email_res.data:
                reply_to_msg_id = email_res.data.get("gmail_message_id")

        # 3. Obtain active Gmail SDK client with silent token rotation
        print(f"[DRAFT SERVICE LOG 3/6] Fetching valid Google OAuth credentials for account {account_id}")
        gmail_client = await self.core_auth.get_authenticated_gmail_client(account_id)

        # 4. Construct base64url MIME email message
        print(f"[DRAFT SERVICE LOG 4/6] Building base64url MIME message for recipients {payload.recipient_to}")
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
        print(f"[DRAFT SERVICE LOG 5/6] Executing Gmail API users().drafts().create()")
        gmail_draft_id = None
        error_log = None
        try:
            gmail_res = gmail_client.users().drafts().create(userId="me", body=draft_payload).execute()
            gmail_draft_id = gmail_res.get("id")
            print(f"[DRAFT SERVICE LOG 5/6 SUCCESS] Gmail draft ID created: {gmail_draft_id}")
        except Exception as e:
            error_log = f"Gmail draft sync failed: {str(e)}"
            print(f"[DRAFT WARNING] {error_log}")
            import traceback
            traceback.print_exc()

        # 6. Insert record into public.email_drafts
        print(f"[DRAFT SERVICE LOG 6/6] Inserting record into public.email_drafts and processing task resolutions")
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

                # Re-evaluate thread workflow status automatically
                await self.synchronizer.sync_thread_status(thread_id, account_id)
            except Exception as ex:
                print(f"[DRAFT RESOLUTIONS WARNING] Failed to persist task resolutions or sync thread status: {ex}")

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
        """Updates draft fields in public.email_drafts, syncs to Gmail, and re-evaluates thread workflow_status."""
        draft_res = self.db.table("email_drafts") \
            .select("*") \
            .eq("id", draft_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not draft_res.data:
            raise KeyError(f"Draft {draft_id} not found or access denied.")

        draft = draft_res.data
        thread_id = draft.get("thread_id")
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
                gmail_client = await self.core_auth.get_authenticated_gmail_client(account_id)
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

            # Re-evaluate thread workflow status
            if thread_id:
                await self.synchronizer.sync_thread_status(thread_id, account_id)

        # Re-fetch updated draft
        refreshed = self.db.table("email_drafts").select("*").eq("id", draft_id).single().execute()
        refreshed_data = refreshed.data
        refreshed_data["resolved_task_ids"] = payload.resolved_task_ids if payload.resolved_task_ids is not None else []
        return refreshed_data

    async def send_draft(self, user_id: str, account_id: str, draft_id: str) -> Dict[str, Any]:
        """Sends the draft via Gmail API (users().drafts().send), marks status = 'sent', and updates thread workflow_status."""
        draft_res = self.db.table("email_drafts") \
            .select("*") \
            .eq("id", draft_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not draft_res.data:
            raise KeyError(f"Draft {draft_id} not found or access denied.")

        draft = draft_res.data
        thread_id = draft.get("thread_id")
        gmail_draft_id = draft.get("gmail_draft_id")

        if gmail_draft_id:
            try:
                gmail_client = await self.core_auth.get_authenticated_gmail_client(account_id)
                gmail_client.users().drafts().send(userId="me", body={"id": gmail_draft_id}).execute()
            except Exception as e:
                print(f"[DRAFT SEND WARNING] Gmail draft send failed: {e}")

        now_iso = datetime.now(timezone.utc).isoformat()
        self.db.table("email_drafts").update({"status": "sent", "updated_at": now_iso}).eq("id", draft_id).execute()

        # Update thread workflow status upon sending (e.g. shifts to 'awaiting_reply' or 'informational')
        if thread_id:
            try:
                await self.synchronizer.sync_thread_status(thread_id, account_id)
            except Exception as ex:
                print(f"[DRAFT SEND WARNING] Thread status sync failed: {ex}")

        refreshed = self.db.table("email_drafts").select("*").eq("id", draft_id).single().execute()
        return refreshed.data
