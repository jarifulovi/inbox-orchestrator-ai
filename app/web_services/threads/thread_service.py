# app/web_services/threads/thread_service.py
import base64
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client, reset_supabase_client
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
            offset: int = 0,
            workflow_status: Optional[str] = None,
            priority: Optional[str] = None,
            q: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches parent thread records dynamically with status/priority/keyword filtering,
        resolves the latest email sender & security trust level, bulk-counts pending tasks,
        and returns real priority & workflow metadata with safe defaults.
        """
        # 1. Fetch account email
        account_email = ""
        try:
            acc_res = self.db.table("connected_accounts").select("provider_email").eq("id", account_id).single().execute()
            if acc_res and acc_res.data:
                account_email = acc_res.data.get("provider_email") or ""
        except Exception as e:
            if "ConnectionTerminated" in str(e) or "RemoteProtocolError" in str(e):
                self.db = reset_supabase_client()
                try:
                    acc_res = self.db.table("connected_accounts").select("provider_email").eq("id", account_id).single().execute()
                    if acc_res and acc_res.data:
                        account_email = acc_res.data.get("provider_email") or ""
                except Exception as retry_e:
                    print(f"[THREADS WARNING] Retry fetch provider_email failed: {retry_e}")
            else:
                print(f"[THREADS WARNING] Failed to fetch provider_email for connected account {account_id}: {e}")

        # 2. Fetch threads with filters
        try:
            query = self.db.table("email_threads") \
                .select("*") \
                .eq("connected_account_id", account_id)

            if workflow_status and workflow_status.strip() and workflow_status.strip().lower() != "all":
                query = query.eq("workflow_status", workflow_status.strip().lower())

            if priority and priority.strip() and priority.strip().lower() != "all":
                query = query.eq("priority", priority.strip().lower())

            if q and q.strip():
                keyword = q.strip()
                # Pre-fetch matching thread IDs from emails table where sender or sender_name matches keyword
                matched_thread_ids = set()
                try:
                    matched_emails_res = self.db.table("emails") \
                        .select("thread_id") \
                        .eq("connected_account_id", account_id) \
                        .or_(f"sender.ilike.%{keyword}%,sender_name.ilike.%{keyword}%") \
                        .limit(100) \
                        .execute()
                    if matched_emails_res.data:
                        matched_thread_ids = {str(e["thread_id"]) for e in matched_emails_res.data if e.get("thread_id")}
                except Exception as match_err:
                    print(f"[THREADS SEARCH WARNING] Sender match pre-query failed: {match_err}")

                if matched_thread_ids:
                    t_ids_str = ",".join(matched_thread_ids)
                    query = query.or_(f"subject.ilike.%{keyword}%,id.in.({t_ids_str})")
                else:
                    query = query.ilike("subject", f"%{keyword}%")

            threads_res = query.order("last_message_at", desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            threads = threads_res.data or []
        except Exception as e:
            if "ConnectionTerminated" in str(e) or "RemoteProtocolError" in str(e):
                self.db = reset_supabase_client()
                try:
                    # Re-build query with fresh client
                    query = self.db.table("email_threads").select("*").eq("connected_account_id", account_id)
                    if workflow_status and workflow_status.strip() and workflow_status.strip().lower() != "all":
                        query = query.eq("workflow_status", workflow_status.strip().lower())
                    if priority and priority.strip() and priority.strip().lower() != "all":
                        query = query.eq("priority", priority.strip().lower())
                    if q and q.strip():
                        query = query.ilike("subject", f"%{q.strip()}%")
                    threads_res = query.order("last_message_at", desc=True).range(offset, offset + limit - 1).execute()
                    threads = threads_res.data or []
                except Exception as retry_e:
                    print(f"[THREADS ERROR] Retry fetch email_threads failed: {retry_e}")
                    return []
            else:
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
            e_res = self.db.table("emails") \
                .select("id, thread_id, sender, sender_name, received_at, ai_metadata") \
                .in_("thread_id", thread_ids) \
                .order("received_at", desc=True) \
                .execute()
            
            for e in (e_res.data or []):
                t_id = e.get("thread_id")
                if not t_id:
                    continue
                emails_by_thread[t_id] = emails_by_thread.get(t_id, 0) + 1

                # Capture latest email details per thread
                if t_id not in latest_email_info:
                    sender_email = e.get("sender", "")
                    sender_name = e.get("sender_name")
                    if not sender_name:
                        sender_name = sender_email.split("<")[0].strip() if "<" in sender_email else sender_email

                    sec_meta = (e.get("ai_metadata") or {}).get("security_analysis") or {}
                    sec_level = sec_meta.get("security_trust_level", "unverified")

                    latest_email_info[t_id] = {
                        "sender_name": sender_name,
                        "sender_email": sender_email,
                        "security_trust_level": sec_level
                    }
        except Exception as ex:
            print(f"[THREADS WARNING] Bulk email resolution failed: {ex}")

        # 4. Bulk count pending tasks per thread
        tasks_counts = {}
        try:
            tasks_res = self.db.table("tasks") \
                .select("id, thread_id") \
                .in_("thread_id", thread_ids) \
                .eq("status", "pending") \
                .execute()
            
            for task in (tasks_res.data or []):
                t_id = task.get("thread_id")
                if t_id:
                    tasks_counts[t_id] = tasks_counts.get(t_id, 0) + 1
        except Exception as ex:
            print(f"[THREADS WARNING] Bulk task counting failed: {ex}")

        # 5. Format threads payload
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
        Fetches detailed thread information in 1 single API call:
        - Thread record metadata & workflow status / priority
        - All emails belonging to thread (with decoded body text, sender info, security trust level, & facts)
        - Actionable tasks linked to thread
        """
        # Fetch thread record
        t_res = self.db.table("email_threads").select("*").eq("id", thread_id).eq("connected_account_id", account_id).single().execute()
        if not t_res.data:
            raise KeyError(f"Thread {thread_id} not found.")

        thread = t_res.data

        # Fetch thread emails
        e_res = self.db.table("emails").select("*").eq("thread_id", thread_id).order("received_at", desc=False).execute()
        raw_emails = e_res.data or []

        # Fetch email_facts for all emails in this thread
        email_ids = [e["id"] for e in raw_emails if e.get("id")]
        facts_by_email = {}
        if email_ids:
            try:
                facts_res = self.db.table("email_facts").select("*").in_("email_id", email_ids).execute()
                for fact in (facts_res.data or []):
                    e_id = fact.get("email_id")
                    if e_id not in facts_by_email:
                        facts_by_email[e_id] = []
                    facts_by_email[e_id].append(fact)
            except Exception as ex:
                print(f"[THREADS WARNING] Failed to fetch email_facts for thread {thread_id}: {ex}")

        # Format and decode emails
        formatted_emails = []
        overall_security_level = "unverified"

        for e in raw_emails:
            e_id = e["id"]
            sender = e.get("sender") or ""
            sender_name = e.get("sender_name")
            if not sender_name:
                sender_name = sender.split("<")[0].strip() if "<" in sender else sender

            # Extract body text
            body = e.get("body") or ""
            if not body:
                payload_node = e.get("payload") or {}
                parts = payload_node.get("parts", [])
                if not parts and "body" in payload_node:
                    body_data = payload_node["body"].get("data", "")
                    if body_data:
                        body = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8", errors="ignore")
                elif parts:
                    body = self._extract_body_text(parts)

            # Security metadata
            ai_metadata = e.get("ai_metadata") or {}
            sec_meta = ai_metadata.get("security_analysis") or {}
            sec_level = sec_meta.get("security_trust_level", "unverified")
            if sec_level in ["trusted", "suspicious", "neutral"]:
                overall_security_level = sec_level

            security_analysis_list = []
            if sec_meta:
                spf_res = sec_meta.get("raw_spf_result")
                dkim_res = sec_meta.get("raw_dkim_result")
                security_analysis_list = [{
                    "email_id": e_id,
                    "spf_pass": (spf_res == "pass" if spf_res else False),
                    "dkim_pass": (dkim_res == "pass" if dkim_res else False),
                    "security_trust_level": sec_level,
                    "security_trust_score": sec_meta.get("security_trust_score", 0.0),
                }]

            formatted_emails.append({
                "id": e_id,
                "thread_id": thread_id,
                "sender": sender,
                "sender_name": sender_name,
                "recipient_to": e.get("recipient_to") or [],
                "subject": e.get("subject") or "(No Subject)",
                "snippet": e.get("snippet") or "",
                "body": body,
                "received_at": e.get("received_at"),
                "email_facts": facts_by_email.get(e_id, []),
                "email_security_analysis": security_analysis_list,
                "security_trust_level": sec_level
            })

        # Fetch thread tasks
        task_res = self.db.table("tasks").select("*").eq("thread_id", thread_id).execute()
        tasks = task_res.data or []

        # Enrich thread record
        thread["security_trust_level"] = overall_security_level
        thread["tasks_count"] = len(tasks)

        return {
            "thread": thread,
            "emails": formatted_emails,
            "tasks": tasks
        }

    async def update_thread_status(self, thread_id: str, account_id: str, workflow_status: str) -> Dict[str, Any]:
        """
        Updates workflow_status for a specific thread record owned by connected_account_id.
        If workflow_status is 'unarchive' or 'unarchived', dynamically re-evaluates the true active status
        ('needs_action', 'awaiting_reply', 'informational', 'follow_up') based on real-time thread facts & emails.
        """
        status_clean = (workflow_status or "").strip().lower()

        if status_clean in ("unarchive", "unarchived"):
            from app.core.services.threads.thread_rule_service import ThreadRuleService
            rule_service = ThreadRuleService()

            # Fetch thread details
            t_res = self.db.table("email_threads").select("*").eq("id", thread_id).eq("connected_account_id", account_id).single().execute()
            if not t_res.data:
                raise KeyError(f"Thread {thread_id} not found or access denied.")
            thread = t_res.data

            # Fetch account provider email
            acc_res = self.db.table("connected_accounts").select("provider_email").eq("id", account_id).single().execute()
            user_email = (acc_res.data or {}).get("provider_email") or ""

            # Fetch emails
            e_res = self.db.table("emails").select("*").eq("thread_id", thread_id).order("received_at", desc=True).execute()
            emails = e_res.data or []

            # Check pending tasks
            tasks_res = self.db.table("tasks").select("id").eq("thread_id", thread_id).eq("status", "pending").execute()
            has_pending_tasks = bool(tasks_res.data)

            # Re-evaluate active status
            status_clean = rule_service.derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=has_pending_tasks,
                ignore_archived=True
            )

        if status_clean not in VALID_WORKFLOW_STATUSES:
            raise ValueError(f"Invalid workflow_status '{workflow_status}'. Must be one of {VALID_WORKFLOW_STATUSES}")

        res = self.db.table("email_threads") \
            .update({"workflow_status": status_clean}) \
            .eq("id", thread_id) \
            .eq("connected_account_id", account_id) \
            .execute()

        if not res.data:
            raise KeyError(f"Thread {thread_id} not found or access denied.")

        return res.data[0]

    def _extract_body_text(self, parts: list) -> str:
        """
        Helper function to iterate over Gmail payload parts and decode readable text,
        explicitly preferring text/html content to preserve layout structure.
        """
        html_content, text_content = self._extract_body_parts(parts)
        return html_content or text_content

    def _extract_body_parts(self, parts: list) -> tuple:
        html_content = ""
        text_content = ""
        for part in parts:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data", "")

            if body_data:
                decoded = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8", errors="ignore")
                if mime_type == "text/html":
                    html_content = decoded
                elif mime_type == "text/plain" and not text_content:
                    text_content = decoded

            if "parts" in part:
                sub_html, sub_text = self._extract_body_parts(part["parts"])
                if sub_html:
                    html_content = sub_html
                if sub_text and not text_content:
                    text_content = sub_text

        return html_content, text_content

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

    async def generate_user_thread_summary(self, thread_id: str, account_id: str) -> dict:
        """
        Executes user-initiated thread summary generation using UserThreadSummaryService.
        Persists updated summary, priority, summary_generated_at, and context_memory to DB.
        """
        from app.web_services.threads.user_summary_service import UserThreadSummaryService
        from app.core.services.threads.thread_core_service import ThreadCoreService
        from datetime import datetime, timezone

        # 1. Fetch target thread & verify ownership
        thread_res = self.db.table("email_threads") \
            .select("*") \
            .eq("id", thread_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not thread_res.data:
            raise KeyError(f"Thread {thread_id} not found or access denied.")

        thread = thread_res.data

        # 2. Fetch all emails associated with thread (ordered by received_at DESC, newest first)
        emails_res = self.db.table("emails") \
            .select("id, body, sender, sender_name, received_at, snippet") \
            .eq("thread_id", thread_id) \
            .order("received_at", desc=True) \
            .execute()

        emails = emails_res.data or []
        if not emails:
            raise ValueError(f"No email messages found for thread {thread_id}.")

        # 3. Fetch any existing email facts and tasks for supplementary context
        email_ids = [e["id"] for e in emails]
        facts_res = self.db.table("email_facts") \
            .select("*") \
            .in_("email_id", email_ids) \
            .execute()
        facts = facts_res.data or []

        tasks_res = self.db.table("tasks") \
            .select("*") \
            .eq("thread_id", thread_id) \
            .execute()
        thread_tasks = tasks_res.data or []
        pending_tasks = [t for t in thread_tasks if t.get("status") == "pending"]

        # 4. Execute user summary generation via UserThreadSummaryService
        summary_service = UserThreadSummaryService()
        output = summary_service.generate_summary_via_llm(
            thread_subject=thread.get("subject") or "No Subject",
            emails=emails,
            facts=facts,
            pending_tasks=pending_tasks,
            existing_summary=thread.get("summary")
        )

        # 5. Build updated context_memory and persist to email_threads DB table
        core_service = ThreadCoreService(summary_service.llm)
        context_memory = core_service.prepare_context_memory(emails, output.summary)
        summary_generated_at = datetime.now(timezone.utc).isoformat()
        priority_val = (output.priority or "medium").lower()

        self.db.table("email_threads").update({
            "summary": output.summary,
            "priority": priority_val,
            "summary_generated_at": summary_generated_at,
            "context_memory": context_memory
        }).eq("id", thread_id).execute()

        # 6. Re-fetch refreshed thread details for frontend response
        refreshed_thread = await self.get_thread_details(thread_id, account_id)

        return {
            "summary": output.summary,
            "priority": priority_val,
            "key_takeaways": output.key_takeaways or [],
            "summary_generated_at": summary_generated_at,
            "thread": refreshed_thread
        }
