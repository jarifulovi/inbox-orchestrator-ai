# app/core/workers/sync_worker.py
import asyncio
from datetime import datetime, timezone
from supabase import Client
from app.db.supabase import get_supabase_client
from app.core.services.auth_service import ConnectedAccountService
from app.core.services.gmail_service import GmailIngestionService
from app.core.services.ml_service import MLEngineService


class EmailSyncWorker:
    def __init__(self, db_client: Client = None):
        self.supabase = db_client or get_supabase_client()
        self.auth_manager = ConnectedAccountService(db_client=self.supabase)
        self.ml_engine = MLEngineService()

        self.INITIAL_BATCH_SIZE = 50
        self.FORCING_BACKFILL_BATCH_SIZE = 10

    async def run_sync_cycle(self):
        """Main runner loop scanning for active user connections."""
        print(f"[WORKER WAKEUP] Starting sync cycle sweep at {datetime.now(timezone.utc)}")

        response = self.supabase.table("connected_accounts") \
            .select("*") \
            .eq("is_active", True) \
            .eq("provider", "google") \
            .execute()

        accounts = response.data
        if not accounts:
            print("[WORKER] No active email connections found.")
            return

        for account in accounts:
            try:
                await self._process_account(account)
            except Exception as e:
                print(f"[WORKER ERROR] Processing failed for account {account.get('provider_email')}: {str(e)}")
                continue

    async def _process_account(self, account: dict):
        account_id = account["id"]
        cursor = account.get("sync_cursor")
        email_address = account.get("provider_email")

        print(f"\n[WORKER] Ingesting state for: {email_address}...")

        # 1. Initialize authenticated Gmail client and bound service layers
        gmail_client = await self.auth_manager.get_authenticated_gmail_client(account_id)
        ingestion_service = GmailIngestionService(gmail_client=gmail_client)

        emails_to_process = []
        next_cursor = None

        # Clean and sanitize the database cursor value defensively
        sanitized_cursor = str(cursor).strip() if cursor else ""

        # 2. Dual-Phase Ingestion Router Logic
        if not sanitized_cursor or sanitized_cursor.lower() == "none" or sanitized_cursor == "":
            print(f"[ROUTE -> INITIAL FETCH] Pulling first historical batch...")
            batch_result = await ingestion_service.fetch_historical_batch(max_results=self.INITIAL_BATCH_SIZE)
            emails_to_process = batch_result["emails"]

            # FIX: Your service keys are flipped. Treat history_id as the pagination token block if it contains the massive string.
            # To be 100% foolproof, check if next_page_token looks like a massive token string.
            next_cursor = batch_result.get("next_page_token") if len(
                str(batch_result.get("next_page_token"))) > 10 else batch_result.get("history_id")

        elif len(sanitized_cursor) > 10:  # FIX: Real page tokens are very long digit strings, while history IDs are shorter integers.
            print(f"[ROUTE -> CONTINUING FETCH] Pagination token detected. Fetching next chunk...")
            batch_result = await ingestion_service.fetch_historical_batch(page_token=sanitized_cursor,
                                                                          max_results=self.INITIAL_BATCH_SIZE)
            emails_to_process = batch_result["emails"]

            # FIX: Maintain the page token assignment logic
            next_cursor = batch_result.get("next_page_token") if len(
                str(batch_result.get("next_page_token"))) > 10 else batch_result.get("history_id")

        else:
            print(f"[ROUTE -> DELTA SYNC] Account caught up. Pulling incremental additions...")
            try:
                # Real history IDs are short (like 58868)
                delta_result = await ingestion_service.fetch_delta_changes(start_history_id=sanitized_cursor)
                emails_to_process = delta_result["emails"]
                next_cursor = delta_result["history_id"]
            except Exception as history_error:
                print(f"[WORKER WARNING] History token expired for {email_address}. Forcing mini backfill.")
                batch_result = await ingestion_service.fetch_historical_batch(
                    max_results=self.FORCING_BACKFILL_BATCH_SIZE)
                emails_to_process = batch_result["emails"]

                # FIX: Handle fallback assignment smoothly
                next_cursor = batch_result.get("next_page_token") if len(str(batch_result.get("next_page_token"))) > 10 else batch_result.get("history_id")


        # =====================================================================
        # 3. Relational Ingestion Stage: Parent Threads -> Child Messages
        # =====================================================================
        if emails_to_process:
            print(f"[WORKER DB] Mapping {len(emails_to_process)} incoming items to thread containers...")

            # Step A: Format and bulk-upsert Parent Thread Frameworks
            thread_records = ingestion_service.format_thread_records(emails_to_process, account_id)
            self.supabase.table("email_threads").upsert(thread_records,
                                                        on_conflict="connected_account_id,gmail_thread_id").execute()

            # Step B: Re-query database to resolve newly generated structural Parent UUIDs
            gmail_thread_ids = [t["gmail_thread_id"] for t in thread_records]
            thread_lookup_res = self.supabase.table("email_threads") \
                .select("id", "gmail_thread_id") \
                .eq("connected_account_id", account_id) \
                .in_("gmail_thread_id", gmail_thread_ids) \
                .execute()

            thread_uuid_map = {row["gmail_thread_id"]: row["id"] for row in thread_lookup_res.data}

            # Run Native Batch ML Engine calculations on the chunk
            enriched_batch_payloads = await self.ml_engine.run_batch_inference(
                email_nodes=emails_to_process,
                historical_context=[]
            )

            # Step C: Format child message records combining raw text data + new ML output nodes
            message_records = ingestion_service.format_message_records(
                emails_to_process=emails_to_process,
                enriched_batch_payloads=enriched_batch_payloads,
                thread_uuid_map=thread_uuid_map,
                account_id=account_id
            )

            # Bulk transactional upsert straight into your archive table repository
            self.supabase.table("emails").upsert(
                message_records,
                on_conflict="connected_account_id,gmail_message_id").execute()
            print(f"[DATABASE SUCCESS] Committed {len(message_records)} fully processed items into public.emails.")

        # 4. Advance tracking cursor metrics safely back to Supabase
        self.supabase.table("connected_accounts").update({
            "sync_cursor": next_cursor,
            "last_sync_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", account_id).execute()

        print(f"[WORKER SUCCESS] Sync complete for {email_address}. Cursor advanced to: '{next_cursor}'")



if __name__ == "__main__":
    worker = EmailSyncWorker()
    asyncio.run(worker.run_sync_cycle())