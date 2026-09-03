from datetime import datetime, timezone, timedelta
from app.core.db.supabase import get_supabase_client
from app.core.llm.client import LLMClient
from app.core.services.threads.thread_core_service import ThreadCoreService
from app.core.ml_models.unified_constants import ELIGIBLE_TASK_FACT_TYPES


class ThreadOrchestrator:
    def __init__(self, llm_client: LLMClient | None = None):
        self.db = get_supabase_client()
        self.llm = llm_client or LLMClient()
        self.orchestration_service = ThreadCoreService(self.llm)

    async def update_sla_breached_threads(self):
        """
        Single batch update query: transitions threads in 'awaiting_reply' to 'follow_up' 
        if the last message was sent >= 48 hours ago.
        """
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        try:
            self.db.table("email_threads") \
                .update({
                    "workflow_status": "follow_up"
                }) \
                .eq("workflow_status", "awaiting_reply") \
                .lte("last_message_at", cutoff_iso) \
                .execute()
        except Exception as e:
            print(f"⚠️ [ThreadOrchestrator] SLA update failed: {e}")

    async def run_cycle(self):
        """
        Main worker cycle that processes un-orchestrated threads in batches.
        Resolves tasks, extracts new commitments, and updates thread-level workflow state.
        """
        print("\n=== [ThreadOrchestrator] Starting Processing Cycle ===")

        try:
            # 0. Execute single batch update for SLA-breached threads (>48h awaiting_reply -> follow_up)
            await self.update_sla_breached_threads()
            # 1. Fetch up to 50 active threads that need processing (excluding archived)
            threads_res = self.db.table("email_threads") \
                .select("*") \
                .eq("is_processed", False) \
                .neq("workflow_status", "archived") \
                .order("last_message_at") \
                .limit(50) \
                .execute()

            threads = threads_res.data or []
            if not threads:
                print("[ThreadOrchestrator] No un-processed threads found.")
                return

            print(f"[ThreadOrchestrator] Processing batch of {len(threads)} threads...")

            for thread in threads:
                try:
                    await self._orchestrate_single_thread(thread)
                except Exception as e:
                    print(f"❌ [ThreadOrchestrator ERROR] Failed thread {thread['id']}: {e}")

        except Exception as e:
            print(f"❌ [ThreadOrchestrator ERROR] Processing cycle failed: {e}")

        print("=== [ThreadOrchestrator] Cycle Complete ===\n")

    async def _orchestrate_single_thread(self, thread: dict):
        thread_id = thread["id"]
        account_id = thread["connected_account_id"]

        # 1. Fetch connected account metadata
        acc_data = self._fetch_account_metadata(account_id)
        if not acc_data:
            print(f"[ThreadOrchestrator] Connected account not found for thread {thread_id}. Skipping.")
            return

        user_id = acc_data["user_id"]
        user_email = acc_data["provider_email"]

        # 2. Fetch emails, facts, and tasks
        emails = self._fetch_thread_emails(thread_id)
        if not emails:
            print(f"[ThreadOrchestrator] No email messages found for thread {thread_id}. Marking processed.")
            self.db.table("email_threads").update({"is_processed": True}).eq("id", thread_id).execute()
            return

        facts = self._fetch_thread_facts([e["id"] for e in emails])
        thread_tasks = self._fetch_thread_tasks(thread_id)

        # 3. Domain Partitioning via ThreadCoreService
        pending_tasks, facts_to_process = self.orchestration_service.partition_unprocessed_facts(
            thread=thread,
            emails=emails,
            facts=facts,
            thread_tasks=thread_tasks
        )

        # 4. LLM-Bypass Check (No new actionable items)
        if not facts_to_process:
            self._handle_llm_bypass(thread, emails, user_email, pending_tasks)
            return

        # 5. LLM Orchestration & Task Execution
        self._handle_llm_orchestration(
            thread=thread,
            emails=emails,
            user_id=user_id,
            account_id=account_id,
            user_email=user_email,
            facts_to_process=facts_to_process,
            pending_tasks=pending_tasks
        )

    # -------------------------------------------------------------------------
    # PRIVATE HELPER METHODS
    # -------------------------------------------------------------------------

    def _fetch_user_settings(self, user_id: str) -> dict:
        try:
            res = self.db.auth.admin.get_user_by_id(user_id)
            if res and hasattr(res, "user") and res.user:
                meta = res.user.user_metadata or {}
                return meta.get("settings") or {}
        except Exception as e:
            print(f"[ThreadOrchestrator] Failed to fetch user_settings for {user_id}: {e}")
        return {}

    def _fetch_account_metadata(self, account_id: str) -> dict | None:
        res = self.db.table("connected_accounts") \
            .select("user_id, provider_email") \
            .eq("id", account_id) \
            .single() \
            .execute()
        return res.data

    def _fetch_thread_emails(self, thread_id: str) -> list:
        res = self.db.table("emails") \
            .select("id, body, sender, sender_name, received_at, snippet") \
            .eq("thread_id", thread_id) \
            .order("received_at", desc=True) \
            .execute()
        return res.data or []

    def _fetch_thread_facts(self, email_ids: list[str]) -> list:
        if not email_ids:
            return []
        res = self.db.table("email_facts") \
            .select("*") \
            .in_("email_id", email_ids) \
            .in_("fact_type", ELIGIBLE_TASK_FACT_TYPES) \
            .execute()
        return res.data or []

    def _fetch_thread_tasks(self, thread_id: str) -> list:
        res = self.db.table("tasks") \
            .select("*") \
            .eq("thread_id", thread_id) \
            .execute()
        return res.data or []

    def _save_thread_state(self, thread_id: str, workflow_status: str, priority: str, summary: str, context_memory: dict):
        self.db.table("email_threads").update({
            "workflow_status": workflow_status,
            "priority": priority.lower(),
            "summary": summary,
            "context_memory": context_memory,
            "is_processed": True,
            "summary_generated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", thread_id).execute()

    def _handle_llm_bypass(self, thread: dict, emails: list, user_email: str, pending_tasks: list):
        thread_id = thread["id"]
        print(f"⚡ [ThreadOrchestrator] Bypassing LLM for thread {thread_id} (No new action items).")
        summary, priority, _ = self.orchestration_service.generate_rule_based_fallback(thread, emails)
        workflow_status = self.orchestration_service.derive_workflow_status(
            thread=thread,
            emails=emails,
            user_email=user_email,
            has_pending_tasks=len(pending_tasks) > 0
        )
        context_memory = self.orchestration_service.prepare_context_memory(emails, summary)
        self._save_thread_state(thread_id, workflow_status, priority, summary, context_memory)
        print(f"✔ [ThreadOrchestrator] (Bypassed) Thread {thread_id} -> status: {workflow_status}, priority: {priority}")

    def _handle_llm_orchestration(
        self,
        thread: dict,
        emails: list,
        user_id: str,
        account_id: str,
        user_email: str,
        facts_to_process: list,
        pending_tasks: list
    ):
        thread_id = thread["id"]
        default_anchor = thread.get("last_message_at") or datetime.now(timezone.utc).isoformat()
        facts_payload = self.orchestration_service.prepare_facts_payload(facts_to_process, default_anchor)
        existing_summary = thread.get("summary")

        # Python Criteria 1-3 Pre-Check for Auto-Draft Toggle
        newest_email = emails[0] if emails else {}
        newest_sender = (newest_email.get("sender") or "").lower()
        is_external_sender = bool(newest_sender and user_email.lower() not in newest_sender)

        # Check active draft in DB
        active_draft_res = self.db.table("email_drafts") \
            .select("id") \
            .eq("thread_id", thread_id) \
            .eq("connected_account_id", account_id) \
            .in_("status", ["draft", "pending_approval"]) \
            .limit(1) \
            .execute()
        no_active_draft = not bool(active_draft_res.data)

        # Read user profile AI settings
        user_settings = self._fetch_user_settings(user_id)
        user_allows_auto_draft = user_settings.get("enable_auto_draft", False)
        enable_auto_task = user_settings.get("enable_auto_task", True)
        summary_format = user_settings.get("summary_format", "paragraph")
        ai_model = user_settings.get("ai_model", "gemini-3.5-flash")

        # Enable auto-draft prompt toggle if user settings allow it, incoming external email on actionable thread without active draft
        enable_auto_draft = user_allows_auto_draft and is_external_sender and no_active_draft

        if existing_summary and len(emails) > 1:
            pending_tasks_payload = [{"id": t["id"], "title": t["title"]} for t in pending_tasks]
            new_email_snippet = newest_email.get("snippet") or (newest_email.get("body")[:300] if newest_email.get("body") else "New message received.")

            response = self.orchestration_service.orchestrate_thread_update_via_llm(
                thread_subject=thread.get("subject") or "No Subject",
                existing_summary=existing_summary,
                pending_tasks=pending_tasks_payload,
                new_actions_payload=facts_payload,
                new_email_snippet=new_email_snippet,
                anchor_date=default_anchor,
                enable_auto_draft=enable_auto_draft,
                summary_format=summary_format,
                model=ai_model
            )
        else:
            email_manifest = self.orchestration_service.prepare_email_manifest(emails)
            response = self.orchestration_service.orchestrate_thread_via_llm(
                thread_subject=thread.get("subject") or "No Subject",
                actions_payload=facts_payload,
                email_manifest=email_manifest,
                anchor_date=default_anchor,
                enable_auto_draft=enable_auto_draft,
                summary_format=summary_format,
                model=ai_model
            )

        if not response.has_actionable_tasks:
            summary, _, _ = self.orchestration_service.generate_rule_based_fallback(thread, emails)
            thread_priority = "low"
            thread_summary = response.thread_summary or existing_summary or summary
            new_tasks = []

            workflow_status = self.orchestration_service.derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=len(pending_tasks) > 0
            )
        else:
            new_tasks = self.orchestration_service.build_task_records(
                response=response,
                facts_to_process=facts_to_process,
                thread_id=thread_id,
                user_id=user_id,
                account_id=account_id
            )

            if new_tasks and enable_auto_task:
                self.db.table("tasks") \
                    .upsert(new_tasks, on_conflict="user_id, action_fingerprint") \
                    .execute()

            workflow_status = self.orchestration_service.derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=(len(pending_tasks) > 0 or len(new_tasks) > 0)
            )
            thread_priority = response.thread_priority or "medium"
            thread_summary = response.thread_summary or (thread.get("summary") or "No Summary")

            # Handle Auto-Draft persistence if generated
            if response.auto_draft and response.auto_draft.can_generate:
                print(f"✨ [ThreadOrchestrator] Auto-draft generated for thread {thread_id}. Persisting pending_approval draft...")
                try:
                    from app.core.services.drafts.draft_core_service import CoreDraftService

                    core_draft_service = CoreDraftService(self.db)
                    recipients = response.auto_draft.recipient_to or [newest_email.get("sender") or ""]
                    cleaned_recipients = [r for r in recipients if r]
                    draft_subject = response.auto_draft.subject or f"Re: {thread.get('subject', '')}"

                    import asyncio
                    asyncio.create_task(
                        core_draft_service.create_draft(
                            user_id=user_id,
                            account_id=account_id,
                            thread_id=thread_id,
                            recipient_to=cleaned_recipients,
                            subject=draft_subject,
                            body=response.auto_draft.body,
                            resolved_task_ids=[],
                            generation_context={
                                "source": "auto_worker",
                                "can_generate": response.auto_draft.can_generate,
                                "reason": response.auto_draft.reason
                            },
                            status="pending_approval"
                        )
                    )
                except Exception as e:
                    print(f"⚠️ [ThreadOrchestrator WARNING] Auto-draft persistence failed: {e}")

        context_memory = self.orchestration_service.prepare_context_memory(emails, thread_summary)
        self._save_thread_state(thread_id, workflow_status, thread_priority, thread_summary, context_memory)
        print(f"✔ [ThreadOrchestrator] Orchestrated thread {thread_id} -> status: {workflow_status}, priority: {thread_priority}")
