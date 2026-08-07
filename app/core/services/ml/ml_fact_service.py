from typing import Any
from dateutil import parser
from app.core.ml_models.fact_extractor.fact_extractor import FactExtractor
from app.core.schemas.email_facts import EmailFactBatchResponse
from app.core.ml_models.unified_constants import FACT_EXTRACTOR_MODEL_VERSION


class MLFactService:
    def __init__(self):
        self.fact_extractor_pipeline = FactExtractor()

    def extract_facts_selectively(
            self,
            safe_nodes: list[dict],
            predictions: list[Any]
    ) -> list[EmailFactBatchResponse]:
        """
        Assigns categories to safe nodes and extracts structured NLP facts.
        """
        for node, pred in zip(safe_nodes, predictions):
            if isinstance(pred, dict):
                node["category"] = pred.get("label")
            elif pred is not None:
                node["category"] = getattr(pred, "label", None)

        return self.fact_extractor_pipeline.predict(safe_nodes)

    async def persist_email_facts(
            self,
            db_client,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Persists NLP fact extraction outputs into email_facts table.
        One email -> multiple fact rows.
        """
        if not email_records or not ml_batch_outputs:
            return

        email_map = {email["id"]: email for email in email_records if email.get("id")}

        fact_rows = []
        for i, ml in enumerate(ml_batch_outputs):
            email_id = ml.get("id")
            email = email_map.get(email_id) if email_id else None
            if not email and i < len(email_records):
                email = email_records[i]

            if not email:
                continue

            raw_facts_payload = ml.get("actions", []) or []

            fact_items = []
            if isinstance(raw_facts_payload, dict):
                fact_items = raw_facts_payload.get("facts", []) or []
            elif isinstance(raw_facts_payload, list):
                fact_items = raw_facts_payload

            if not isinstance(fact_items, list):
                continue

            # Resolve user_id, connected_account_id, and anchor_date
            user_id = email.get("user_id")
            if not user_id and "connected_accounts" in email:
                connected_account = email.get("connected_accounts") or {}
                user_id = connected_account.get("user_id")
            connected_account_id = email.get("connected_account_id")
            anchor_date = self.safe_parse_datetime(email.get("received_at"))

            for fact in fact_items:
                if not isinstance(fact, dict):
                    print(f"[ML WARNING] Skipping malformed fact item: {fact}")
                    continue

                fact_rows.append({
                    "email_id": email["id"],
                    "user_id": user_id,
                    "connected_account_id": connected_account_id,
                    "sentence_index": fact.get("sentence_index"),
                    "fact_type": fact.get("fact_type"),
                    "payload": fact.get("payload", {}),
                    "source_sentence": fact.get("source_sentence"),
                    "anchor_date": anchor_date,
                    "confidence": fact.get("confidence", 1.0),
                    "model_version": fact.get("model_version", FACT_EXTRACTOR_MODEL_VERSION)
                })

        if not fact_rows:
            print("[ML FACTS] No facts extracted")
            return

        try:
            db_client.table("email_facts").insert(fact_rows).execute()
            print(f"[ML SUCCESS] Stored {len(fact_rows)} email facts")
        except Exception as e:
            print(f"[ML ERROR] Email facts insert failed: {str(e)}")

    @staticmethod
    def safe_parse_datetime(value):
        """Converts extracted deadline into TIMESTAMPTZ-safe format."""
        if not value:
            return None
        try:
            return parser.parse(value).isoformat()
        except Exception:
            return None
