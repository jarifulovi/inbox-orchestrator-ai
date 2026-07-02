import uuid
from datetime import datetime, timezone, timedelta
from app.core.db.supabase import get_supabase_client
from app.core.services.tasks.task_generation import TaskGenerationService
from app.core.llm.client import LLMClient


class TaskGenerationWorker:
    def __init__(self, llm_client: LLMClient | None = None):
        self.db = get_supabase_client()
        self.llm_client = llm_client or LLMClient()
        self.generation_service = TaskGenerationService(self.llm_client)
        self.LIMIT_TASK_GENERATION = 30

    async def run_generation_cycle(self):
        """
        Fetches un-analyzed extracted actions, generates tasks for them using Gemini,
        and persists the new task blueprints into the database.
        """
        print("[TaskGenerationWorker] Starting generation cycle...")

        try:
            # 1. Fetch recent extracted actions and their associated emails and connected accounts
            # We do this instead of a complex NOT IN query for simplicity, filtering locally for now.
            actions_res = self.db.table("extracted_actions").select(
                "id, email_id, user_id, verb_primitive, object_primitive, source_sentence, parsed_deadline, "
                "emails(id, thread_id, body, connected_account_id, "
                "connected_accounts(user_id))"
            ).order("extracted_at", desc=True).limit(self.LIMIT_TASK_GENERATION).execute()
            
            actions = actions_res.data
            if not actions:
                print("[TaskGenerationWorker] No extracted actions found.")
                return

            action_ids = [a["id"] for a in actions]

            # 2. Find which of these actions already have tasks generated
            existing_tasks_res = self.db.table("tasks").select("extracted_action_id").in_("extracted_action_id", action_ids).execute()
            existing_action_ids = {t["extracted_action_id"] for t in existing_tasks_res.data}

            actions_to_process = [a for a in actions if a["id"] not in existing_action_ids]

            if not actions_to_process:
                print("[TaskGenerationWorker] All recent actions already have tasks.")
                return

            print(f"[TaskGenerationWorker] Found {len(actions_to_process)} actions needing tasks.")

            # 3. Process actions in a single batch
            actions_data = []
            for action in actions_to_process:
                # Prepare the action data for the LLM prompt
                action_data = {
                    "id": action.get("id"),
                    "verb_primitive": action.get("verb_primitive"),
                    "object_primitive": action.get("object_primitive"),
                    "source_sentence": action.get("source_sentence"),
                    "anchor_date": action.get("anchor_date") or action.get("emails", {}).get("received_at") # Fallback to email received_at if available
                }
                actions_data.append(action_data)
            
            print(f"[TaskGenerationWorker] Sending {len(actions_data)} actions for batch generation.")
            batch_blueprint = self.generation_service.generate_batch_task(actions_data)
            
            if not batch_blueprint or not batch_blueprint.tasks:
                print("[TaskGenerationWorker] No tasks generated from batch.")
                return

            new_tasks = []
            
            # Create a lookup dictionary for original actions by ID
            actions_by_id = {a["id"]: a for a in actions_to_process}

            for blueprint in batch_blueprint.tasks:
                action = actions_by_id.get(blueprint.extracted_action_id)
                if not action:
                    print(f"[TaskGenerationWorker] Action {blueprint.extracted_action_id} not found in source batch.")
                    continue

                if not blueprint.is_actionable_task:
                    print(f"[TaskGenerationWorker] LLM rejected action {action['id']} as non-actionable. Skipping.")
                    continue

                email = action.get("emails")
                if not email:
                    continue

                # Parse user_id (with fallback for legacy records missing user_id on extracted_action)
                user_id = action.get("user_id")
                if not user_id:
                    connected_account = email.get("connected_accounts") or {}
                    user_id = connected_account.get("user_id")

                if not user_id:
                    print(f"[TaskGenerationWorker] Missing user_id for action {action['id']}")
                    continue

                # Calculate fingerprint deterministically
                fingerprint = self.generation_service.generate_action_fingerprint(
                    email["thread_id"], 
                    action.get("verb_primitive", ""), 
                    action.get("object_primitive", "")
                )

                # Build the DBTaskRow-compatible dict
                task_row = {
                    "id": str(uuid.uuid4()),
                    "extracted_action_id": action["id"],
                    "email_id": email["id"],
                    "thread_id": email["thread_id"],
                    "user_id": user_id,
                    "title": blueprint.title,
                    "status": "pending",
                    "priority": blueprint.priority,
                    "action_fingerprint": fingerprint,
                    "enriched_context": {
                        "source_sentence": action.get("source_sentence")
                    },
                    "due_date": blueprint.due_date_iso,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                new_tasks.append(task_row)

            # 4. Bulk upsert the new tasks efficiently
            if new_tasks:
                self.db.table("tasks") \
                    .upsert(new_tasks, on_conflict="user_id, action_fingerprint") \
                    .execute()
                
                print(f"[TaskGenerationWorker] Sent {len(new_tasks)} tasks to DB (duplicates automatically ignored).")
            else:
                print("[TaskGenerationWorker] No tasks were successfully generated.")

        except Exception as e:
            print(f"[TaskGenerationWorker] Error during cycle: {e}")
