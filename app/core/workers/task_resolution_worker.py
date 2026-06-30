from datetime import datetime, timezone
from app.db.supabase import get_supabase_client
from app.core.services.tasks.task_resolution import TaskResolutionService
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import WorkerThreadContext


class TaskResolutionWorker:
    def __init__(self, llm_client: LLMClient | None = None):
        self.db = get_supabase_client()
        self.llm_client = llm_client or LLMClient()
        self.resolution_service = TaskResolutionService(self.llm_client)
        self.LIMIT_TASK_RESOLUTION = 10

    async def run_resolution_cycle(self):
        """
        Fetches pending tasks and groups them by thread, finds new incoming emails
        on those threads, and evaluates via Gemini if the task has been resolved.
        """
        print("[TaskResolutionWorker] Starting resolution cycle...")

        try:
            # 1. Fetch pending tasks
            tasks_res = self.db.table("tasks").select("*").eq("status", "pending").execute()
            pending_tasks = tasks_res.data

            if not pending_tasks:
                print("[TaskResolutionWorker] No pending tasks found.")
                return

            print(f"[TaskResolutionWorker] Found {len(pending_tasks)} pending tasks.")

            # Group tasks by thread_id and action_fingerprint (assuming same action fingerprint evaluates together)
            # Or just group by thread_id for evaluation context.
            threads = {}
            for task in pending_tasks:
                thread_id = task.get("thread_id")
                if not thread_id:
                    continue
                if thread_id not in threads:
                    threads[thread_id] = []
                threads[thread_id].append(task)

            # 2. For each thread, find recent emails that arrived AFTER the tasks were created/updated
            # We will use the most recent task creation/update time in the thread as a baseline
            updates_to_apply = []

            for thread_id, thread_tasks in threads.items():
                min_task_time = min(t.get("created_at", datetime.min.replace(tzinfo=timezone.utc).isoformat()) for t in thread_tasks)
                
                # Fetch new emails for this thread
                # We filter by ingested_at > min_task_time (or received_at) and cap it to 10 latest messages
                emails_res = self.db.table("emails").select("body, received_at").eq("thread_id", thread_id).gte("received_at", min_task_time).order("received_at", desc=True).limit(self.LIMIT_TASK_RESOLUTION).execute()
                new_emails = emails_res.data

                if not new_emails:
                    continue
                
                # Group by fingerprint to build contexts
                contexts_by_fingerprint = {}
                for task in thread_tasks:
                    fp = task["action_fingerprint"]
                    if fp not in contexts_by_fingerprint:
                        contexts_by_fingerprint[fp] = {
                            "thread_id": thread_id,
                            "action_fingerprint": fp,
                            "pending_tasks": [],
                            "new_email_bodies": [e["body"] for e in new_emails if e.get("body")]
                        }
                    contexts_by_fingerprint[fp]["pending_tasks"].append(task)

                # 3. Evaluate each context
                for fp, context in contexts_by_fingerprint.items():
                    # context is WorkerThreadContext
                    task_updates = self.resolution_service.evaluate_thread_resolution(context)
                    updates_to_apply.extend(task_updates)

            # 4. Apply updates
            if updates_to_apply:
                print(f"[TaskResolutionWorker] Applying {len(updates_to_apply)} task resolution updates.")
                for update in updates_to_apply:
                    self.db.table("tasks").update({
                        "status": update["status"],
                        "enriched_context": update["enriched_context"],
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }).eq("id", update["id"]).execute()
            else:
                print("[TaskResolutionWorker] No tasks resolved in this cycle.")

        except Exception as e:
            print(f"[TaskResolutionWorker] Error during cycle: {e}")
