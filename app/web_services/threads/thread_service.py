# app/web_services/threads/thread_service.py
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client
from app.core.schemas.email_threads import VALID_WORKFLOW_STATUSES, VALID_THREAD_PRIORITIES


class ThreadWebService:
    """
    Dedicated web service for Thread operations:
    thread listing, workflow status evaluation, message aggregation, and thread sync.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client or get_supabase_client()

    async def get_user_threads(
            self,
            account_id: str,
            limit: int = 20,
            offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetches parent thread records dynamically, resolves the latest email sender & security trust level,
        bulk-counts pending tasks, and returns real priority & workflow metadata with safe defaults.
        """
        # 1. Fetch account email
        account_email = ""
        try:
            acc_res = self.db.table("connected_accounts").select("provider_email").eq("id", account_id).single().execute()
            if acc_res and acc_res.data:
                account_email = acc_res.data.get("provider_email") or ""
        except Exception as e:
            print(f"[THREADS WARNING] Failed to fetch provider_email for connected account {account_id}: {e}")

        # 2. Fetch threads
        try:
            threads_res = self.db.table("email_threads") \
                .select("*") \
                .eq("connected_account_id", account_id) \
                .order("last_message_at", desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            threads = threads_res.data or []
        except Exception as e:
            print(f"[THREADS ERROR] Failed to fetch email_threads: {e}")
            return []

        if not threads:
            return []

        thread_ids = [t["id"] for t in threads if t.get("id")]
        if not thread_ids:
            return []

        # 3. Bulk fetch emails for these threads to resolve latest sender info, latest email security_trust_level, and message_count
        emails_by_thread = {}
        latest_email_info = {}
        try:
            emails_res = self.db.table("emails") \
                .select("thread_id, sender, sender_name, received_at, ai_metadata") \
                .in_("thread_id", thread_ids) \
                .order("received_at", desc=True) \
                .execute()

            for e in (emails_res.data or []):
                t_id = e["thread_id"]
                if t_id not in emails_by_thread:
                    emails_by_thread[t_id] = 0
                    sec_meta = (e.get("ai_metadata") or {}).get("security_analysis") or {}
                    latest_email_info[t_id] = {
                        "sender_name": e.get("sender_name") or (e.get("sender", "").split("<")[0].strip() if e.get("sender") else "Unknown"),
                        "sender_email": e.get("sender", "unknown@email.com"),
                        "security_trust_level": sec_meta.get("security_trust_level", "unverified")
                    }
                emails_by_thread[t_id] += 1
        except Exception as e:
            print(f"[THREADS WARNING] Failed to fetch bulk emails for threads: {e}")

        # 4. Bulk count pending tasks for these threads
        tasks_counts = {}
        try:
            tasks_res = self.db.table("tasks") \
                .select("thread_id, status") \
                .in_("thread_id", thread_ids) \
                .execute()

            for t in (tasks_res.data or []):
                t_id = t.get("thread_id")
                st = t.get("status")
                if t_id and st == "pending":
                    tasks_counts[t_id] = tasks_counts.get(t_id, 0) + 1
        except Exception as e:
            print(f"[THREADS WARNING] Failed to bulk count tasks for threads: {e}")

        # 5. Format response to match frontend thread schema
        formatted_threads = []
        for t in threads:
            t_id = t["id"]
            e_info = latest_email_info.get(t_id, {})
            sender_name = e_info.get("sender_name", "Unknown")
            sender_email = e_info.get("sender_email", "unknown@email.com")
            security_trust_level = e_info.get("security_trust_level", "unverified")

            # Priority from email_threads DB column (default: "medium")
            raw_priority = (t.get("priority") or "").lower()
            priority = raw_priority if raw_priority in VALID_THREAD_PRIORITIES else "medium"

            # Workflow status from email_threads DB column (default: "informational")
            raw_workflow = (t.get("workflow_status") or "").lower()
            workflow_status = raw_workflow if raw_workflow in VALID_WORKFLOW_STATUSES else "informational"

            # Tasks count from tasks table
            tasks_count = tasks_counts.get(t_id, 0)

            # Unread status
            unread_count = t.get("unread_messages_count", 0)
            unread = bool(unread_count > 0 or t.get("unread", False))

            message_count = emails_by_thread.get(t_id, 1)

            formatted_threads.append({
                "id": t_id,
                "subject": t.get("subject") or "(No Subject)",
                "sender_name": sender_name,
                "sender_email": sender_email,
                "preview": t.get("snippet") or "",
                "summary": t.get("summary") or "No Summary",
                "priority": priority,
                "workflow_status": workflow_status,
                "security_trust_level": security_trust_level,
                "tasks_count": tasks_count,
                "timestamp": t.get("last_message_at"),
                "unread": unread,
                "message_count": message_count,
                "account_email": account_email
            })

        return formatted_threads

    async def get_thread_details(self, thread_id: str, account_id: str) -> Dict[str, Any]:
        """
        Fetches detailed thread information including all emails, thread summary, tasks, and context memory.
        """
        # Fetch thread record
        t_res = self.db.table("email_threads").select("*").eq("id", thread_id).eq("connected_account_id", account_id).single().execute()
        if not t_res.data:
            raise KeyError(f"Thread {thread_id} not found.")

        thread = t_res.data

        # Fetch thread emails
        e_res = self.db.table("emails").select("*").eq("thread_id", thread_id).order("received_at", asc=True).execute()
        emails = e_res.data or []

        # Fetch thread tasks
        task_res = self.db.table("tasks").select("*").eq("thread_id", thread_id).execute()
        tasks = task_res.data or []

        return {
            "thread": thread,
            "emails": emails,
            "tasks": tasks
        }

    async def sync_user_inbox(self, account_id: str) -> bool:
        """
        Trigger backend email ingestion synchronously, skipping ML for performance.
        """
        from app.core.workers.sync_worker import EmailSyncWorker
        from app.core.services.auth_service import ConnectedAccountService

        auth_service = ConnectedAccountService(db_client=self.db)
        account = auth_service.get_account_by_id(account_id)
        if not account:
            raise Exception("Connected account profile not found.")

        worker = EmailSyncWorker(db_client=self.db)
        await worker._process_account(account, skip_ml=True)
        return True
