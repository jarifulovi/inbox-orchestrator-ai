import hashlib
from datetime import datetime, timezone
from app.core.db.supabase import get_supabase_client
from app.core.llm.client import LLMClient
from app.core.services.content_compressor import ContentCompressorService
from app.core.services.tasks.thread_orchestration import ThreadOrchestrationService


class ThreadOrchestrator:
    def __init__(self, llm_client: LLMClient | None = None):
        self.db = get_supabase_client()
        self.llm = llm_client or LLMClient()
        self.orchestration_service = ThreadOrchestrationService(self.llm)

    async def run_cycle(self):
        """
        Main worker cycle that processes un-orchestrated threads in batches.
        Resolves tasks, extracts new commitments, and updates thread-level workflow state.
        """
        print("\n=== [ThreadOrchestrator] Starting Processing Cycle ===")

        try:
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

        # 3. Fetch all extracted actions for these emails
        email_ids = [e["id"] for e in emails]
        actions_res = self.db.table("extracted_actions") \
            .select("*") \
            .in_("email_id", email_ids) \
            .execute()

        actions = actions_res.data or []

        # 4. Fetch all tasks associated with this thread
        tasks_res = self.db.table("tasks") \
            .select("*") \
            .eq("thread_id", thread_id) \
            .execute()

        thread_tasks = tasks_res.data or []

        # 5. Partition tasks & actions
        pending_tasks = [t for t in thread_tasks if t["status"] == "pending"]
        tasked_action_ids = {t["extracted_action_id"] for t in thread_tasks if t["extracted_action_id"]}
        actions_to_process = [a for a in actions if a["id"] not in tasked_action_ids]

        # -------------------------------------------------------------
        # LLM-BYPASS CHECK
        # If there are no pending tasks and no new actions to process,
        # we bypass Gemini entirely to save tokens and execution time.
        # -------------------------------------------------------------
        if not pending_tasks and not actions_to_process:
            print(f"⚡ [ThreadOrchestrator] Bypassing LLM for thread {thread_id} (No pending tasks or action items).")
            summary, priority, expects_reply = self.orchestration_service.generate_rule_based_fallback(
                thread, emails
            )

            # Derive workflow status locally
            workflow_status = "informational"
            latest_email = emails[0]
            latest_sender = latest_email.get("sender", "").lower()
            is_user_sender = user_email.lower() in latest_sender if user_email else False

            if is_user_sender and expects_reply:
                workflow_status = "awaiting_reply"

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
        actions_payload = [
            {
                "id": a["id"],
                "verb_primitive": a.get("verb_primitive"),
                "object_primitive": a.get("object_primitive"),
                "source_sent": a.get("source_sentence"),
                "raw_entities": a.get("raw_entities"),
                "anchor_date": a.get("parsed_deadline") or thread.get("last_message_at")
            }
            for a in actions_to_process
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
            pending_tasks=pending_tasks,
            actions_payload=actions_payload,
            email_manifest=email_manifest,
            anchor_date=thread.get("last_message_at") or datetime.now(timezone.utc).isoformat()
        )

        # 8. Apply modifications:
        # A. Upsert generated tasks
        new_tasks = []
        actions_by_id = {a["id"]: a for a in actions_to_process}

        for blueprint in response.task_generations:
            if not blueprint.is_actionable_task:
                continue
            action = actions_by_id.get(blueprint.extracted_action_id)
            if not action:
                continue

            fingerprint = self._generate_action_fingerprint(
                thread_id,
                action.get("verb_primitive", ""),
                action.get("object_primitive", "")
            )

            new_tasks.append({
                "extracted_action_id": blueprint.extracted_action_id,
                "email_id": action["email_id"],
                "thread_id": thread_id,
                "user_id": user_id,
                "title": blueprint.title,
                "status": "pending",
                "priority": blueprint.priority,
                "intent_label": blueprint.intent_label,
                "action_fingerprint": fingerprint,
                "due_date": blueprint.due_date_iso
            })

        if new_tasks:
            self.db.table("tasks") \
                .upsert(new_tasks, on_conflict="user_id, action_fingerprint") \
                .execute()

        # B. Update resolved/completed tasks
        completed_ids = set()
        for resolution in response.task_resolutions:
            if resolution.status in ("completed", "dismissed"):
                matching_task = next((t for t in pending_tasks if t["id"] == resolution.id), None)
                if not matching_task:
                    continue

                completed_ids.add(resolution.id)
                enriched = matching_task.get("enriched_context") or {}
                enriched["resolution_summary"] = resolution.resolution_summary

                self.db.table("tasks").update({
                    "status": resolution.status,
                    "enriched_context": enriched,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", resolution.id).execute()

        # C. Derive overall workflow state
        # 1. Any remaining unresolved tasks (excluding the ones we just completed, including new ones)
        has_unresolved_tasks = False
        for t in pending_tasks:
            if t["id"] not in completed_ids:
                has_unresolved_tasks = True
                break
        if new_tasks:
            has_unresolved_tasks = True

        workflow_status = "informational"
        if has_unresolved_tasks:
            workflow_status = "needs_action"
        else:
            # Check if last sender was user (emails[0] is the latest email)
            latest_email = emails[0]
            latest_sender = latest_email.get("sender", "").lower()
            is_user_sender = user_email.lower() in latest_sender if user_email else False

            if is_user_sender and response.last_user_email_expects_reply:
                workflow_status = "awaiting_reply"

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
            "thread_summary": response.thread_summary
        }

        # E. Update the thread record
        self.db.table("email_threads").update({
            "workflow_status": workflow_status,
            "priority": response.thread_priority.lower(),
            "summary": response.thread_summary,
            "context_memory": context_memory,
            "is_processed": True,
            "summary_generated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", thread_id).execute()

        print(f"✔ [ThreadOrchestrator] Orchestrated thread {thread_id} -> status: {workflow_status}, priority: {response.thread_priority}")
