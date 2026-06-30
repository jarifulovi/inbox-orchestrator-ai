import uuid
from datetime import datetime, timezone, timedelta
from app.db.supabase import get_supabase_client
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
                "id, email_id, verb_primitive, object_primitive, source_sentence, parsed_deadline, "
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

            # 3. Process each action
            new_tasks = []
            for action in actions_to_process:
                email = action.get("emails")
                if not email:
                    continue
                
                email_body = email.get("body", "")
                if not email_body:
                    continue

                # Prepare the action data for the LLM prompt
                action_data = {
                    "verb_primitive": action.get("verb_primitive"),
                    "object_primitive": action.get("object_primitive"),
                    "source_sentence": action.get("source_sentence"),
                    "parsed_deadline": action.get("parsed_deadline")
                }

                blueprint = self.generation_service.generate_task(action_data, email_body)
                if not blueprint:
                    continue
                
                if not blueprint.is_actionable_task:
                    print(f"[TaskGenerationWorker] LLM rejected action {action['id']} as non-actionable. Skipping.")
                    # Optionally, you could insert it with status='dismissed' if you want to track skipped items, 
                    # but skipping avoids DB bloat. For now we just skip.
                    continue

                # Parse user_id
                connected_account = email.get("connected_accounts") or {}
                user_id = connected_account.get("user_id")
                if not user_id:
                    print(f"[TaskGenerationWorker] Missing user_id for action {action['id']}")
                    continue

                # Calculate due_date
                due_date_iso = None
                if blueprint.due_date_days_from_now is not None:
                    due_date = datetime.now(timezone.utc) + timedelta(days=blueprint.due_date_days_from_now)
                    due_date_iso = due_date.isoformat()
                elif action.get("parsed_deadline"):
                    due_date_iso = action["parsed_deadline"]

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
                    "action_fingerprint": blueprint.action_fingerprint,
                    "enriched_context": {
                        "source_sentence": action.get("source_sentence")
                    },
                    "due_date": due_date_iso,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
                new_tasks.append(task_row)

            # 4. Bulk insert the new tasks
            if new_tasks:
                self.db.table("tasks").insert(new_tasks).execute()
                print(f"[TaskGenerationWorker] Successfully inserted {len(new_tasks)} new tasks.")
            else:
                print("[TaskGenerationWorker] No tasks were successfully generated.")

        except Exception as e:
            print(f"[TaskGenerationWorker] Error during cycle: {e}")
