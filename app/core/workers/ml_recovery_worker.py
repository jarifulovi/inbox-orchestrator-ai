import asyncio
from datetime import datetime, timezone
from supabase import Client

from app.core.services.ml_service import MLEngineService
from app.db.supabase import get_supabase_client



class MLRecoveryWorker:
    def __init__(self, ml_engine=None, supabase_client: Client = None):
        self.ml_engine = ml_engine or MLEngineService()
        self.supabase = supabase_client or get_supabase_client()
        self.BATCH_SIZE = 50

    async def run_recovery_cycle(self):
        print("\n[ML RECOVERY] Checking for emails missing ML analysis...")

        try:
            # 1. Fetch raw emails that lack matching email_classifications
            # We select email fields and left-join email_classifications, filtering for null
            response = self.supabase.table("emails") \
                .select("*, email_classifications(id)") \
                .is_("email_classifications", "null") \
                .limit(self.BATCH_SIZE) \
                .execute()

            unprocessed_emails = response.data or []

            if not unprocessed_emails:
                print("[ML RECOVERY] Everything is up to date. No catch-up required.")
                return

            print(f"[ML RECOVERY] Found {len(unprocessed_emails)} emails requiring catch-up processing.")

            # 2. Re-format the DB records into the format your ml_engine expects (email_nodes)
            email_nodes = self._build_email_nodes(unprocessed_emails)

            # 3. Execute batch inference
            print(f"[ML RECOVERY] Executing batch inference on {len(email_nodes)} nodes...")
            ml_batch_outputs = self.ml_engine.run_batch_inference(
                email_nodes=email_nodes,
                historical_context=[]
            )

            # 4. Save the ML outputs
            # Passing raw database records as the 'email_save_res' equivalent
            # so the helper maps UUIDs accurately.
            await self._persist_ml_outputs(unprocessed_emails, ml_batch_outputs)
            print(f"[ML RECOVERY SUCCESS] Successfully caught up {len(email_nodes)} emails!")

        except Exception as e:
            print(f"[ML RECOVERY CRITICAL ERROR] Recovery worker cycle failed: {str(e)}")

    async def _persist_ml_outputs(self, email_records: list, ml_batch_outputs: list[dict]):
        """
        Re-use or adapt your existing ML database persistence logic here.
        Make sure it maps email records to your classifications and actions tables.
        """
        # TODO: We can extract a method in core/services/ml_service.py for resuable ML persistence
        pass

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