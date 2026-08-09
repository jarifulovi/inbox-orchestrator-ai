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
        acc_res = self.db.table("connected_accounts") \
            .select("user_id, provider_email") \
            .eq("id", account_id) \
            .single() \
            .execute()

        if not acc_res.data:
            print(f"[ThreadOrchestrator] Connected account not found for thread {thread_id}. Skipping.")
            return

        user_id = acc_res.data["user_id"]
        user_email = acc_res.data["provider_email"]

        # 2. Fetch all emails associated with the thread (newest first)
        emails_res = self.db.table("emails") \
            .select("id, body, sender, sender_name, received_at, snippet") \
            .eq("thread_id", thread_id) \
            .order("received_at", desc=True) \
            .execute()

        emails = emails_res.data or []
        if not emails:
            print(f"[ThreadOrchestrator] No email messages found for thread {thread_id}. Marking processed.")
            self.db.table("email_threads").update({"is_processed": True}).eq("id", thread_id).execute()
            return

        # 3. Fetch all task-eligible facts for these emails
        email_ids = [e["id"] for e in emails]
        facts_res = self.db.table("email_facts") \
            .select("*") \
            .in_("email_id", email_ids) \
            .in_("fact_type", ELIGIBLE_TASK_FACT_TYPES) \
            .execute()

        facts = facts_res.data or []

        # 4. Fetch all tasks associated with this thread
        tasks_res = self.db.table("tasks") \
            .select("*") \
            .eq("thread_id", thread_id) \
            .execute()

        thread_tasks = tasks_res.data or []

        # 5. Partition tasks & facts (Isolate ONLY new email facts via message_manifest in context_memory)
        pending_tasks = [t for t in thread_tasks if t["status"] == "pending"]
        tasked_fact_ids = {t["email_fact_id"] for t in thread_tasks if t.get("email_fact_id")}
        existing_summary = thread.get("summary")
        context_memory = thread.get("context_memory") or {}
        message_manifest = context_memory.get("message_manifest") or []
        processed_email_ids = {m["message_id"] for m in message_manifest if isinstance(m, dict) and "message_id" in m}

        if existing_summary and processed_email_ids:
            # Re-processing existing thread: isolate emails that have not been in message_manifest yet
            new_emails = [e for e in emails if e["id"] not in processed_email_ids]
            new_email_ids = {e["id"] for e in new_emails}
            facts_to_process = [
                f for f in facts 
                if f["email_id"] in new_email_ids and f["id"] not in tasked_fact_ids
            ]
        else:
            # Initial thread orchestration run
            facts_to_process = [f for f in facts if f["id"] not in tasked_fact_ids]

        # -------------------------------------------------------------
        # LLM-BYPASS CHECK
        # If there are no new actions to process, we bypass Gemini entirely
        # to save tokens and execution time.
        # -------------------------------------------------------------
        if not facts_to_process:
            print(f"⚡ [ThreadOrchestrator] Bypassing LLM for thread {thread_id} (No new action items).")
            summary, priority, does_need_auto_draft = self.orchestration_service.generate_rule_based_fallback(
                thread, emails
            )

            # Derive workflow status via ThreadCoreService
            workflow_status = self.orchestration_service.derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=len(pending_tasks) > 0
            )

            context_memory = self.orchestration_service.prepare_context_memory(emails, summary)

            self.db.table("email_threads").update({
                "workflow_status": workflow_status,
                "priority": priority.lower(),
                "summary": summary,
                "context_memory": context_memory,
                "is_processed": True,
                "summary_generated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", thread_id).execute()

            print(f"✔ [ThreadOrchestrator] (Bypassed) Thread {thread_id} -> status: {workflow_status}, priority: {priority}")
            return

        # 6. Format context data for Gemini via ThreadCoreService
        default_anchor = thread.get("last_message_at") or datetime.now(timezone.utc).isoformat()
        facts_payload = self.orchestration_service.prepare_facts_payload(facts_to_process, default_anchor)
        existing_summary = thread.get("summary")

        # 7. Orchestrate via LLM (Gemini): Initial vs Delta Update Prompt
        if existing_summary and len(emails) > 1:
            # Dual-Phase Update Prompt (Delta Analysis on incoming email)
            pending_tasks_payload = [
                {"id": t["id"], "title": t["title"]}
                for t in pending_tasks
            ]
            newest_email = emails[0] if emails else {}
            new_email_snippet = newest_email.get("snippet") or (newest_email.get("body")[:300] if newest_email.get("body") else "New message received.")

            response = self.orchestration_service.orchestrate_thread_update_via_llm(
                thread_subject=thread.get("subject") or "No Subject",
                existing_summary=existing_summary,
                pending_tasks=pending_tasks_payload,
                new_actions_payload=facts_payload,
                new_email_snippet=new_email_snippet,
                anchor_date=default_anchor
            )
        else:
            # Initial Analysis Prompt for new thread
            email_manifest = self.orchestration_service.prepare_email_manifest(emails)
            response = self.orchestration_service.orchestrate_thread_via_llm(
                thread_subject=thread.get("subject") or "No Subject",
                actions_payload=facts_payload,
                email_manifest=email_manifest,
                anchor_date=default_anchor
            )

        # 8. Apply modifications & extract new tasks:
        if not response.has_actionable_tasks:
            summary, _, does_need_auto_draft = self.orchestration_service.generate_rule_based_fallback(
                thread, emails
            )
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
            new_tasks = []
            facts_by_id = {f["id"]: f for f in facts_to_process}

            for blueprint in response.task_generations:
                if not blueprint.is_actionable_task:
                    continue
                fact = facts_by_id.get(blueprint.email_fact_id)
                if not fact:
                    continue

                payload = fact.get("payload") or {}
                verb = payload.get("action") or ""
                obj = payload.get("object") or ""

                fingerprint = self.orchestration_service.generate_action_fingerprint(
                    thread_id,
                    verb,
                    obj
                )

                new_tasks.append({
                    "email_fact_id": blueprint.email_fact_id,
                    "email_id": fact["email_id"],
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "connected_account_id": account_id,
                    "source": "system",
                    "title": blueprint.title,
                    "status": "pending",
                    "priority": (blueprint.priority or "medium").lower(),
                    "intent_label": blueprint.intent_label,
                    "action_fingerprint": fingerprint,
                    "due_date": blueprint.due_date_iso
                })

            if new_tasks:
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

        # 10. Serialize context memory and update database
        context_memory = self.orchestration_service.prepare_context_memory(emails, thread_summary)

        self.db.table("email_threads").update({
            "workflow_status": workflow_status,
            "priority": thread_priority.lower(),
            "summary": thread_summary,
            "context_memory": context_memory,
            "is_processed": True,
            "summary_generated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", thread_id).execute()

        print(f"✔ [ThreadOrchestrator] Orchestrated thread {thread_id} -> status: {workflow_status}, priority: {thread_priority}")
