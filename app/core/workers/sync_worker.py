# app/core/workers/sync_worker.py
import asyncio
from dateutil import parser
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

        self.INITIAL_BATCH_SIZE = 20
        self.FORCING_BACKFILL_BATCH_SIZE = 10


    async def run_sync_cycle(self):
        print(f"[WORKER WAKEUP] {datetime.now(timezone.utc)}")

        accounts = self.auth_manager.get_active_google_accounts()

        if not accounts:
            print("[WORKER] No active email connections found.")
            return

        for account in accounts:
            try:
                await self._process_account(account)
            except Exception as e:
                print(f"[WORKER ERROR] {account.get('provider_email')}: {e}")


    async def run_initial_backfill(self, account_id: str):
        print(f"📥 [LOAD TEST START] Initializing high-volume sync for Account ID: {account_id}")
        cycle_count = 0

        while True:
            cycle_count += 1
            account = self.auth_manager.get_account_by_id(account_id)
            if not account:
                print(f"❌ [WORKER] Account {account_id} not found or deleted from DB.")
                return

            # 1. Print current batch progress
            print(f"🔄 [BATCH #{cycle_count}] Processing next batch for {account['provider_email']}...")

            try:
                # Execute the heavy fetching, parsing, and database saving
                await self._process_account(account)
            except Exception as e:
                # 2. Catch unexpected failures so your loop doesn't break blindly
                print(f"💥 [CRITICAL CRASH IN BATCH #{cycle_count}] Error: {str(e)}")
                return

            # Refresh the account state from the database
            account = self.auth_manager.get_account_by_id(account_id)

            # 3. Print success indicator when Google pagination finally completes
            if account["sync_mode"] == "ACTIVE":
                print(f"✅ [LOAD TEST SUCCESS] {account['provider_email']} fully backfilled after {cycle_count} batches!")
                break
            # This gives FastAPI a microsecond window to handle incoming /me requests!
            await asyncio.sleep(0.01)

    async def _process_account(self, account: dict):
        account_id = account["id"]
        email_address = account.get("provider_email")

        sync_mode = account.get("sync_mode")
        sync_status = account.get("sync_status")
        cursor = account.get("sync_cursor")

        print(f"\n[WORKER] Processing account: {email_address}")
        print(f"[STATE] mode={sync_mode}, status={sync_status}, cursor={cursor}")

        # 1. Lock account execution (prevents concurrent runs)
        self.supabase.table("connected_accounts").update({
            "sync_status": "SYNCING"
        }).eq("id", account_id).execute()

        gmail_client = await self.auth_manager.get_authenticated_gmail_client(account_id)
        ingestion_service = GmailIngestionService(gmail_client=gmail_client)

        emails_to_process = []
        next_cursor = cursor
        next_mode = sync_mode

        try:

            # =========================================================
            # 2. STATE MACHINE ROUTING (NO CURSOR GUESSING)
            # =========================================================

            if sync_mode in (None, "INITIAL_BACKFILL"):
                print("[ROUTE -> INITIAL BACKFILL]")

                batch_result = await ingestion_service.fetch_historical_batch(
                    max_results=self.INITIAL_BATCH_SIZE
                )

                emails_to_process = batch_result["emails"]
                next_cursor = batch_result.get("next_page_token") or batch_result.get("history_id")
                next_mode = "BACKFILLING"

            elif sync_mode == "BACKFILLING":
                print("[ROUTE -> BACKFILL CONTINUATION]")

                batch_result = await ingestion_service.fetch_historical_batch(
                    page_token=cursor,
                    max_results=self.INITIAL_BATCH_SIZE
                )

                emails_to_process = batch_result["emails"]
                next_cursor = batch_result.get("next_page_token") or batch_result.get("history_id")

                # If no more pages → switch to ACTIVE
                if not batch_result.get("next_page_token"):
                    next_mode = "ACTIVE"

            elif sync_mode == "ACTIVE":
                print("[ROUTE -> DELTA SYNC]")

                try:
                    delta_result = await ingestion_service.fetch_delta_changes(
                        start_history_id=cursor
                    )

                    emails_to_process = delta_result["emails"]
                    next_cursor = delta_result["history_id"]
                    next_mode = "ACTIVE"

                except Exception as e:
                    print(f"[DELTA ERROR] Falling back to mini backfill: {str(e)}")

                    batch_result = await ingestion_service.fetch_historical_batch(
                        max_results=self.FORCING_BACKFILL_BATCH_SIZE
                    )

                    emails_to_process = batch_result["emails"]
                    next_cursor = batch_result.get("history_id") or batch_result.get("next_page_token")
                    next_mode = "BACKFILLING"

            else:
                raise ValueError(f"Unknown sync_mode: {sync_mode}")

            # =========================================================
            # 3. INGESTION PIPELINE (UNCHANGED LOGIC)
            # =========================================================

            if emails_to_process:
                print(f"[DB] Processing {len(emails_to_process)} emails")

                thread_records = ingestion_service.format_thread_records(
                    emails_to_process,
                    account_id
                )

                self.supabase.table("email_threads").upsert(
                    thread_records,
                    on_conflict="connected_account_id,gmail_thread_id"
                ).execute()

                gmail_thread_ids = [t["gmail_thread_id"] for t in thread_records]

                thread_lookup_res = self.supabase.table("email_threads") \
                    .select("id, gmail_thread_id") \
                    .eq("connected_account_id", account_id) \
                    .in_("gmail_thread_id", gmail_thread_ids) \
                    .execute()

                thread_uuid_map = {
                    row["gmail_thread_id"]: row["id"]
                    for row in thread_lookup_res.data
                }
                # Run the ml inference
                ml_batch_outputs = await self.ml_engine.run_batch_inference(
                    email_nodes=emails_to_process,
                    historical_context=[]
                )
                # 2. Build raw email records
                message_records = self._build_email_records(
                    emails_to_process=emails_to_process,
                    thread_uuid_map=thread_uuid_map,
                    account_id=account_id
                )
                # 3. Persist emails first
                self.supabase.table("emails").upsert(
                    message_records,
                    on_conflict="connected_account_id,gmail_message_id"
                ).execute()
                # TODO: ML persistence layer
                # self._persist_ml_outputs(email_records, ml_batch_outputs)
                print(f"[SUCCESS] Ingested {len(message_records)} messages")

            # =========================================================
            # 4. STATE UPDATE (IMPORTANT FIX)
            # =========================================================

            self.supabase.table("connected_accounts").update({
                "sync_cursor": next_cursor,
                "sync_mode": next_mode,
                "sync_status": "IDLE",
                "last_sync_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", account_id).execute()

            print(f"[DONE] {email_address} → mode={next_mode}, cursor={next_cursor}")

        except Exception as e:

            self.supabase.table("connected_accounts").update({
                "sync_status": "FAILED"
            }).eq("id", account_id).execute()

            print(f"[WORKER ERROR] {email_address}: {str(e)}")


    def _build_email_records(
            self,
            emails_to_process: list[dict],
            thread_uuid_map: dict,
            account_id: str
    ) -> list[dict]:

        records = []

        for email in emails_to_process:
            records.append({
                "thread_id": thread_uuid_map[email["thread_id"]],
                "connected_account_id": account_id,
                "gmail_message_id": email["message_id"],
                "sender": email["sender"],
                "sender_name": email.get("sender_name"),
                "recipients": email.get("recipients", []),
                "cc": email.get("cc", []),
                "bcc": email.get("bcc", []),
                "subject": email.get("subject", "(No Subject)"),
                "body": email.get("body_content"),
                "snippet": email.get("snippet", ""),
                "summary": "",
                "processed_by_ai": False,
                "received_at": email.get("date_sent"),
                "raw_payload": email.get("raw_payload")
                # has_attachments used false for now
            })

        return records


    async def _persist_ml_outputs(
            self,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Orchestrates all ML persistence operations.
        """
        await asyncio.gather(
            self._persist_classifications(email_records, ml_batch_outputs),
            self._persist_extracted_actions(email_records, ml_batch_outputs)
        )

    async def _persist_classifications(
            self,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Persists classification outputs into email_classifications table.
        """

        if not email_records or not ml_batch_outputs:
            return

        classification_rows = []

        for email, ml in zip(email_records, ml_batch_outputs):
            classification = ml.get("classification", {})

            classification_rows.append({
                "email_id": email["id"],
                "label_id": self._map_label_to_id(classification.get("category")),
                "label": classification.get("category"),
                "confidence": classification.get("confidence", 0.0),
                "probabilities": classification.get("probabilities", {}),
                "model_version": "v1.0",
                "classified_at": datetime.now(timezone.utc).isoformat()
            })

        try:
            self.supabase.table("email_classifications").upsert(
                classification_rows,
                on_conflict="email_id"
            ).execute()

            print(f"[ML SUCCESS] Stored {len(classification_rows)} classifications")

        except Exception as e:
            print(f"[ML ERROR] Classification insert failed: {str(e)}")


    async def _persist_extracted_actions(
        self,
        email_records: list[dict],
        ml_batch_outputs: list[dict]
    ):
        """
        Persists NLP action extraction outputs into extracted_actions table.
        One email → multiple action rows.
        """

        if not email_records or not ml_batch_outputs:
            return

        action_rows = []

        for email, ml in zip(email_records, ml_batch_outputs):

            actions = ml.get("actions", {})
            action_items = actions.get("action_items", [])

            for action in action_items:

                action_rows.append({
                    "email_id": email["id"],

                    # NOTE: these depend on your action extractor format
                    "verb_primitive": action.get("verb"),
                    "object_primitive": action.get("object"),
                    "source_sentence": action.get("sentence"),

                    "raw_entities": action.get("entities", {}),

                    "parsed_deadline": self._safe_parse_datetime(
                        action.get("deadline")
                    ),

                    "model_version": "v1.0",
                    "extracted_at": datetime.now(timezone.utc).isoformat()
                })

        if not action_rows:
            print("[ML ACTIONS] No actions extracted")
            return

        try:
            self.supabase.table("extracted_actions").insert(
                action_rows
            ).execute()

            print(f"[ML SUCCESS] Stored {len(action_rows)} extracted actions")

        except Exception as e:
            print(f"[ML ERROR] Action insert failed: {str(e)}")


    def _safe_parse_datetime(self, value):
        """
        Converts extracted deadline into TIMESTAMPTZ-safe format.
        """
        if not value:
            return None

        try:
            return parser.parse(value).isoformat()
        except Exception:
            return None


if __name__ == "__main__":
    worker = EmailSyncWorker()
    asyncio.run(worker.run_sync_cycle())