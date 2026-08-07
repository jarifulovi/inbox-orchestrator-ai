import hashlib
from datetime import datetime, timezone, timedelta
from app.core.db.supabase import get_supabase_client
from app.core.llm.client import LLMClient
from app.core.services.content_compressor import ContentCompressorService
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
                    "workflow_status": "follow_up",
                    "updated_at": datetime.now(timezone.utc).isoformat()
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
            # 1. Fetch up to 50 active threads that need processing
            threads_res = self.db.table("email_threads") \
                .select("*") \
                .eq("is_processed", False) \
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

    def _generate_action_fingerprint(self, thread_id: str, verb_primitive: str, object_primitive: str) -> str:
        """Generates a deterministic MD5 fingerprint for a task based on thread and action semantics."""
        raw_string = f"{thread_id}_{verb_primitive}_{object_primitive}".lower()
        return hashlib.md5(raw_string.encode('utf-8')).hexdigest()

    def _derive_workflow_status(
        self,
        thread: dict,
        emails: list,
        user_email: str,
        has_pending_tasks: bool
    ) -> str:
        """
        Derives thread workflow_status following docs/thread_workflow_and_labels_manifest.md:
        1. If has_pending_tasks -> 'needs_action' (includes open questions asked to user)
        2. If thread is already 'archived' -> preserve 'archived' (archived threads ignored for processing)
        3. If 0 pending tasks:
           - Check latest email:
             - If sent by user:
               - Elapsed time >= 48h -> 'follow_up' (SLA threshold)
               - Elapsed time < 48h -> 'awaiting_reply'
             - If third-party sender -> 'informational'
        """
        if has_pending_tasks:
            return "needs_action"

        if thread.get("workflow_status") == "archived":
            return "archived"

        if not emails:
            return "informational"

        latest_email = emails[0]
        latest_sender = (latest_email.get("sender") or "").lower()
        is_user_sender = bool(user_email and user_email.lower() in latest_sender)

        if is_user_sender:
            received_at_str = latest_email.get("received_at")
            hours_elapsed = 0.0
            if received_at_str:
                try:
                    sent_dt = datetime.fromisoformat(received_at_str.replace("Z", "+00:00"))
                    now_dt = datetime.now(timezone.utc)
                    hours_elapsed = (now_dt - sent_dt).total_seconds() / 3600.0
                except Exception:
                    hours_elapsed = 0.0

            if hours_elapsed >= 48.0:
                return "follow_up"
            else:
                return "awaiting_reply"

        return "informational"

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

        # 5. Partition tasks & facts
        pending_tasks = [t for t in thread_tasks if t["status"] == "pending"]
        tasked_fact_ids = {t["email_fact_id"] for t in thread_tasks if t.get("email_fact_id")}
        facts_to_process = [f for f in facts if f["id"] not in tasked_fact_ids]

        # -------------------------------------------------------------
        # LLM-BYPASS CHECK
        # If there are no pending tasks and no new actions to process,
        # -------------------------------------------------------------
        # LLM-BYPASS CHECK
        # If there are no new actions to process, we bypass Gemini entirely
        # to save tokens and execution time.
        # -------------------------------------------------------------
        if not facts_to_process:
            print(f"⚡ [ThreadOrchestrator] Bypassing LLM for thread {thread_id} (No new action items).")
            summary, priority, expects_reply = self.orchestration_service.generate_rule_based_fallback(
                thread, emails
            )

            # Derive workflow status locally via unified helper
            workflow_status = self._derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=len(pending_tasks) > 0
            )

            context_memory = {
                "message_manifest": [
                    {
                        "message_id": e["id"],
                        "sender_name": e["sender_name"],
                        "sender_email": e["sender"],
                        "received_at": e["received_at"],
                        "snippet": e.get("snippet") or (e.get("body")[:200] if e.get("body") else "")
                    }
                    for e in reversed(emails)
                ],
                "aggregated_facts": [],
                "thread_summary": summary
            }

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

        # 6. Format context data for Gemini
        facts_payload = [
            {
                "id": f["id"],
                "verb_primitive": f.get("payload", {}).get("action") if f.get("payload") else None,
                "object_primitive": f.get("payload", {}).get("object") if f.get("payload") else None,
                "source_sent": f.get("source_sentence"),
                "raw_entities": f.get("payload", {}).get("entities") if f.get("payload") else None,
                "anchor_date": f.get("anchor_date") or thread.get("last_message_at")
            }
            for f in facts_to_process
        ]

        email_manifest = [
            {
                "id": e["id"],
                "sender": e["sender"],
                "sender_name": e["sender_name"],
                "received_at": e["received_at"],
                "body_compressed": ContentCompressorService.compress_email_body(e["body"])
            }
            for e in emails
        ]

        # 7. Orchestrate via LLM (Gemini)
        response = self.orchestration_service.orchestrate_thread_via_llm(
            thread_subject=thread.get("subject") or "No Subject",
            actions_payload=facts_payload,
            email_manifest=email_manifest,
            anchor_date=thread.get("last_message_at") or datetime.now(timezone.utc).isoformat()
        )

        # 8. Apply modifications:
        # A. Check if the response reports no actionable tasks (bypass LLM summary/priority)
        if not response.has_actionable_tasks:
            summary, _, expects_reply = self.orchestration_service.generate_rule_based_fallback(
                thread, emails
            )
            thread_priority = "low"
            thread_summary = summary
            new_tasks = []

            # Derive overall workflow state via unified helper
            workflow_status = self._derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=len(pending_tasks) > 0
            )
        else:
            # B. Upsert generated tasks
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

                fingerprint = self._generate_action_fingerprint(
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

            # Derive overall workflow state via unified helper
            workflow_status = self._derive_workflow_status(
                thread=thread,
                emails=emails,
                user_email=user_email,
                has_pending_tasks=(len(pending_tasks) > 0 or len(new_tasks) > 0)
            )

            thread_priority = response.thread_priority or "medium"
            thread_summary = response.thread_summary or (thread.get("summary") or "No Summary")

        # D. Serialize context memory manifest
        context_memory = {
            "message_manifest": [
                {
                    "message_id": e["id"],
                    "sender_name": e["sender_name"],
                    "sender_email": e["sender"],
                    "received_at": e["received_at"],
                    "snippet": e.get("snippet") or (e.get("body")[:200] if e.get("body") else "")
                }
                for e in reversed(emails)  # Chronological order
            ],
            "aggregated_facts": [],
            "thread_summary": thread_summary
        }

        # E. Update the thread record
        self.db.table("email_threads").update({
            "workflow_status": workflow_status,
            "priority": thread_priority.lower(),
            "summary": thread_summary,
            "context_memory": context_memory,
            "is_processed": True,
            "summary_generated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", thread_id).execute()

        print(f"✔ [ThreadOrchestrator] Orchestrated thread {thread_id} -> status: {workflow_status}, priority: {thread_priority}")
