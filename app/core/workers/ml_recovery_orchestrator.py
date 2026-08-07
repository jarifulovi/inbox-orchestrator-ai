from supabase import Client
from app.core.services.ml import MLCoreService
from app.core.db.supabase import get_supabase_client


class MLRecoveryOrchestrator:
    def __init__(self, ml_engine=None, supabase_client: Client | None = None):
        self.ml_engine = ml_engine or MLCoreService()
        self.supabase = supabase_client or get_supabase_client()
        self.BATCH_SIZE = 50

    async def run_recovery_cycle(self):
        print("\n[ML RECOVERY ORCHESTRATOR] Checking for emails missing ML analysis...")

        try:
            # 1. Fetch raw emails that lack category (meaning category is null)
            response = self.supabase.table("emails") \
                .select("*, connected_accounts(user_id)") \
                .is_("category", "null") \
                .order("received_at", desc=True) \
                .limit(self.BATCH_SIZE) \
                .execute()

            unprocessed_emails = response.data or []

            # Populate user_id directly inside unprocessed_emails
            for email in unprocessed_emails:
                connected_account = email.get("connected_accounts") or {}
                email["user_id"] = connected_account.get("user_id")

            if not unprocessed_emails:
                print("[ML RECOVERY ORCHESTRATOR] Everything is up to date. No catch-up required.")
                return

            print(f"[ML RECOVERY ORCHESTRATOR] Found {len(unprocessed_emails)} emails requiring catch-up processing.")

            # 2. Re-format the DB records into the format ml_engine expects (email_nodes)
            email_nodes = self._build_email_nodes(unprocessed_emails)

            # 3. Execute batch inference
            print(f"[ML RECOVERY ORCHESTRATOR] Executing batch inference on {len(email_nodes)} nodes...")
            ml_batch_outputs = self.ml_engine.run_batch_inference(
                email_nodes=email_nodes,
                historical_context=[]
            )

            # 4. Save the ML outputs
            await self.ml_engine.persist_ml_outputs(
                self.supabase,
                unprocessed_emails,
                ml_batch_outputs
            )
            print(f"[ML RECOVERY ORCHESTRATOR SUCCESS] Successfully caught up {len(email_nodes)} emails!")

        except Exception as e:
            print(f"[ML RECOVERY ORCHESTRATOR CRITICAL ERROR] Recovery cycle failed: {str(e)}")

    def _build_email_nodes(self, unprocessed_emails: list[dict]) -> list[dict]:
        """Transforms raw DB email records into the structural format expected by MLEngine."""
        email_nodes = []
        for email in unprocessed_emails:
            email_nodes.append({
                "id": email["id"],
                "gmail_message_id": email.get("gmail_message_id"),
                "thread_id": email.get("thread_id"),
                "connected_account_id": email.get("connected_account_id"),
                "subject": email.get("subject", ""),
                "body": email.get("body", ""),
                "snippet": email.get("snippet", ""),
                "sender": email.get("sender", ""),
                "recipients": email.get("recipients", ""),
                "received_at": email.get("received_at")
            })
        return email_nodes
