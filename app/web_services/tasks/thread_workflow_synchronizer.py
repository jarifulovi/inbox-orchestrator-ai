# app/web_services/tasks/thread_workflow_synchronizer.py
from datetime import datetime, timezone
from typing import Optional
from supabase import Client


class ThreadWorkflowSynchronizer:
    """
    Dedicated class for evaluating and synchronizing thread workflow_status
    whenever task lifecycle events (create, update, delete) occur.
    Ensures operational integrity: raises exceptions on failure to ensure updates fail atomically.
    """

    def __init__(self, db_client: Client):
        self.db = db_client

    async def sync_thread_status(self, thread_id: str, account_id: Optional[str] = None) -> str:
        """
        Evaluates and updates a thread's workflow_status based on remaining tasks and SLA rules:
        1. 'needs_action': 1+ pending tasks exist.
        2. If 0 pending tasks remain:
           - Check latest email in thread:
             - If latest email sent by user < 48h ago -> 'awaiting_reply'
             - If latest email sent by user >= 48h ago -> 'follow_up'
             - If latest email not sent by user -> 'informational'

        Raises Exception if database synchronization fails, preventing partial updates.
        """
        if not thread_id:
            raise ValueError("thread_id is required for workflow status synchronization.")

        # 1. Check remaining pending tasks for this thread
        pending_res = self.db.table("tasks").select("id").eq("thread_id", thread_id).eq("status", "pending").execute()
        pending_tasks = pending_res.data or []

        if len(pending_tasks) > 0:
            target_status = "needs_action"
        else:
            # Check current thread status (preserve 'archived' if set)
            thr_res = self.db.table("email_threads").select("workflow_status, connected_account_id").eq("id", thread_id).execute()
            thr_data = (thr_res.data or [{}])[0]
            if thr_data.get("workflow_status") == "archived":
                return "archived"

            resolved_account_id = account_id or thr_data.get("connected_account_id")

            # Fetch user provider email
            user_email = ""
            if resolved_account_id:
                acc_res = self.db.table("connected_accounts").select("provider_email").eq("id", resolved_account_id).single().execute()
                if acc_res and acc_res.data:
                    user_email = acc_res.data.get("provider_email") or ""

            # Fetch latest email in thread
            email_res = self.db.table("emails").select("sender, received_at").eq("thread_id", thread_id).order("received_at", desc=True).limit(1).execute()
            latest_email = (email_res.data or [{}])[0]

            latest_sender = (latest_email.get("sender") or "").lower()
            is_user_sender = bool(user_email and user_email.lower() in latest_sender)

            if is_user_sender:
                received_at_str = latest_email.get("received_at")
                hours_elapsed = 0.0
                if received_at_str:
                    sent_dt = datetime.fromisoformat(received_at_str.replace("Z", "+00:00"))
                    now_dt = datetime.now(timezone.utc)
                    hours_elapsed = (now_dt - sent_dt).total_seconds() / 3600.0

                # SLA Threshold: < 48 hours = awaiting_reply, >= 48 hours = follow_up
                if hours_elapsed >= 48.0:
                    target_status = "follow_up"
                else:
                    target_status = "awaiting_reply"
            else:
                target_status = "informational"

        # 2. Synchronize thread workflow_status
        upd_res = self.db.table("email_threads").update({"workflow_status": target_status}).eq("id", thread_id).execute()
        if not upd_res.data:
            raise RuntimeError(f"Failed to update workflow_status to '{target_status}' for thread {thread_id}")

        return target_status
