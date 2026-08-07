import asyncio
from typing import Any
from app.core.ml_models.security import PostSecurityValidator
from app.core.ml_models.embedder.embedder import EmailEmbedder
from app.core.ml_models.unified_constants import CLASSIFIER_MODEL_VERSION


class MLPostSecurityService:
    def __init__(self):
        self.post_security_pipeline = PostSecurityValidator()
        self.embedder = EmailEmbedder()

    def evaluate_post_security(
            self,
            safe_nodes: list[dict],
            predictions: list[Any],
            extracted_facts: list[Any],
            historical_context: list[dict] | None = None
    ) -> list[dict]:
        return self.post_security_pipeline.predict(
            safe_nodes, predictions, extracted_facts, historical_context
        )

    def apply_quarantine_fallback(
            self,
            idx: int,
            pred: Any,
            statuses: list[str],
            final_classifications: list[Any],
            final_facts: list[Any],
            final_security: list[Any]
    ) -> None:
        """
        Mutates tracking structures at index `idx` to apply quarantine state
        when Pass 1 Pre-Security checks fail.
        """
        statuses[idx] = "QUARANTINED_PRE_SECURITY"

        final_classifications[idx] = {
            "label_id": -1,
            "label": "spam",
            "confidence": 1.0,
            "probabilities": {}
        }

        final_facts[idx] = {
            "email_id": None,
            "facts": []
        }

        final_security[idx] = {
            "pre_security_passed": pred.get("pre_security_passed", False),
            "security_risks": pred.get("security_risks", []),
            "extracted_spam_score": pred.get("extracted_spam_score"),
            "has_reply_to_mismatch": pred.get("has_reply_to_mismatch", False),
            "is_possible_prompt_injection": pred.get("is_possible_prompt_injection", False),
            "raw_spf_result": pred.get("raw_spf_result"),
            "raw_dkim_result": pred.get("raw_dkim_result"),
            "security_trust_score": float(round(pred["pass1_computed_score"], 2)) if "pass1_computed_score" in pred else 0.00,
            "security_trust_level": "suspicious",
            "is_phishing_anomaly": True,
            "risks_detected": pred["security_risks"] if "security_risks" in pred else ["PRE_SECURITY_VIOLATION"],
            "context_records_evaluated": 0
        }

    async def persist_email_metadata_and_category(
            self,
            db_client,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Persists classification category, structured ai_metadata, and semantic embeddings directly to emails table.
        """
        if not email_records or not ml_batch_outputs:
            return

        email_map = {email["id"]: email for email in email_records if email.get("id")}

        async def _update_single_email(email_id: str, category_name: str, metadata: dict, embedding: list[float] | None):
            try:
                payload = {
                    "category": category_name,
                    "ai_metadata": metadata
                }
                if embedding is not None:
                    payload["embedding"] = embedding
                db_client.table("emails").update(payload).eq("id", email_id).execute()
            except Exception as e:
                print(f"[ML ERROR] Failed to update email {email_id} category/metadata/embedding: {str(e)}")

        documents = []
        ordered_emails = []
        for i, ml in enumerate(ml_batch_outputs):
            email_id = ml.get("id")
            email = email_map.get(email_id) if email_id else None
            if not email and i < len(email_records):
                email = email_records[i]

            if not email:
                print(f"[ML WARNING] Email ID {email_id} not found in email_records. Skipping embedding.")
                continue

            ordered_emails.append(email)
            classification = ml.get("classification", {})
            label_name = classification.get("label") or "UNCATEGORIZED"
            
            raw_payload = email.get("raw_payload") or {}
            label_ids = raw_payload.get("labelIds") or []
            
            raw_facts_payload = ml.get("actions", []) or []
            fact_items = []
            if isinstance(raw_facts_payload, dict):
                fact_items = raw_facts_payload.get("facts", []) or []
            elif isinstance(raw_facts_payload, list):
                fact_items = raw_facts_payload

            doc_parts = [
                f"Subject: {email.get('subject') or ''}",
                f"Category: {label_name}",
                f"Gmail Labels: {', '.join(label_ids)}",
                f"Snippet: {(email.get('snippet') or '')[:400]}",
                "Facts:"
            ]
            for fact in fact_items:
                if isinstance(fact, dict) and fact.get("source_sentence"):
                    doc_parts.append(f"- {fact.get('source_sentence')}")
            
            structured_doc = "\n".join(doc_parts)
            documents.append(structured_doc)

        embeddings = [None] * len(ordered_emails)
        if documents:
            try:
                embeddings = self.embedder.generate_embeddings(documents)
            except Exception as emb_err:
                print(f"[ML ERROR] Failed to generate batch embeddings: {emb_err}")

        update_tasks = []
        for i, (email, ml) in enumerate(zip(ordered_emails, ml_batch_outputs)):
            classification = ml.get("classification", {})
            security = ml.get("security", {})
            status = ml.get("status", "APPROVED")

            label_name = classification.get("label")
            label_id = classification.get("label_id")

            if label_id is None:
                print(f"[ML WARNING] Missing label_id for email {email['id']}. Applying defaults.")
                label_id = -1
                label_name = label_name or "UNCATEGORIZED"

            is_quarantined = (status == "QUARANTINED_PRE_SECURITY")

            ai_metadata = {
                "classifier": {
                    "is_proc": True,
                    "label_id": label_id,
                    "confidence": classification.get("confidence", 0.0),
                    "probabilities": classification.get("probabilities", {}),
                    "model_version": CLASSIFIER_MODEL_VERSION
                },
                "fact_extraction": {
                    "is_proc": not is_quarantined
                },
                "security_analysis": {
                    "is_proc": True,
                    "pre_security_passed": security.get("pre_security_passed", True),
                    "security_risks": security.get("security_risks", []),
                    "extracted_spam_score": security.get("extracted_spam_score"),
                    "has_reply_to_mismatch": security.get("has_reply_to_mismatch", False),
                    "is_possible_prompt_injection": security.get("is_possible_prompt_injection", False),
                    "raw_spf_result": security.get("raw_spf_result"),
                    "raw_dkim_result": security.get("raw_dkim_result"),
                    "security_trust_score": security.get("security_trust_score", 0.0),
                    "security_trust_level": security.get("security_trust_level", "unverified"),
                    "is_phishing_anomaly": security.get("is_phishing_anomaly", False),
                    "risks_detected": security.get("risks_detected", [])
                }
            }

            update_tasks.append(
                _update_single_email(email["id"], label_name, ai_metadata, embeddings[i])
            )

        if update_tasks:
            await asyncio.gather(*update_tasks)
            print(f"[ML SUCCESS] Processed category, metadata, and embedding for {len(update_tasks)} emails")
