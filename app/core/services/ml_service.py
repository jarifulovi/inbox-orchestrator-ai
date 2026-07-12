import asyncio
from datetime import datetime, timezone
from typing import Any, cast
from bs4 import BeautifulSoup
from dateutil import parser

from app.core.ml_models.fact_extractor.fact_extractor import FactExtractor
from app.core.ml_models.classifier.predictor import EmailClassifier
from app.core.ml_models.security import PostSecurityValidator
from app.core.ml_models.security.pre_security import PreSecurityFilter
from app.core.schemas.email_facts import EmailFactBatchResponse
from app.core.ml_models.unified_constants import ACTIONABLE_INTENT_LABELS, CLASSIFIER_LABELS, CLASSIFIER_MODEL_VERSION, \
    FACT_EXTRACTOR_MODEL_VERSION


class MLEngineService:
    def __init__(self):
        print("[ML ENGINE] Initializing Production Native-Batch AI Orchestrator...")
        self.pre_security_engine = PreSecurityFilter()  # Pass 1: Context-free safety filter
        self.classifier_engine = EmailClassifier()  # Pass 2a: Intent categorization
        self.fact_extractor_pipeline = FactExtractor()
        self.post_security_pipeline = PostSecurityValidator()

    def _preprocess_batch(self, email_nodes: list[dict]) -> list[dict]:
        """
        Ingests the pre-parsed 'body' string, normalizes formatting/whitespace,
        and cuts it at a safe length to protect regex engines.
        """
        for node in email_nodes:
            # 1. Strip out html
            raw_input = node.get("body") or node.get("snippet") or ""
            raw_text = self._html_to_text(raw_input)

            # 2. Standardize all line break formats and strip empty trailing gaps
            text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)

            # 3. Truncate at 50,000 characters to prevent backtracking regex freezes
            if len(text) > 50000:
                text = text[:50000].rsplit(" ", 1)[0]

            # 4. Bind the final string directly back to the matrix node
            node["cleaned_body"] = text if text else "[EMPTY_EMAIL]"

        return email_nodes

    def run_batch_inference(
            self,
            email_nodes: list[dict],
            historical_context: list[dict] | None = None
    ) -> list[dict]:
        if not email_nodes:
            return []

        # 1. Clean Text inline directly inside the nodes matrix
        self._preprocess_batch(email_nodes)

        # Pull parameters cleanly out of the mutated node tracking structures
        cleaned_bodies = [node["cleaned_body"] for node in email_nodes]
        raw_payloads = [node.get("raw_payload", {}) for node in email_nodes]

        print(f"[ML INFERENCE] Initiating True Columnar Batch Execution for {len(email_nodes)} emails...")

        # LAYER 1: BATCHED PRE-SECURITY EVALUATION (Pass 1 - Context-Free)
        pre_sec_predictions = self.pre_security_engine.predict(
            email_texts=cleaned_bodies,
            raw_payloads=raw_payloads
        )

        # Isolate clean index positions that are safe to process vs those quarantined
        safe_indices = [i for i, pred in enumerate(pre_sec_predictions) if pred["pre_security_passed"]]

        # Allocate empty tracking structures typed to Any to completely bypass IDE type-checker flags
        final_classifications: list[Any] = [None] * len(email_nodes)
        final_facts: list[Any] = [None] * len(email_nodes)
        final_security: list[Any] = [None] * len(email_nodes)
        statuses = ["APPROVED"] * len(email_nodes)

        # LAYER 2 & 3: CORE BATCHED INFERENCE (Only execute processing on safe data chunks)
        if safe_indices:
            safe_nodes = [email_nodes[i] for i in safe_indices]

            # A. Core Intent Category Inference
            predictions = self._predict_intent_with_gmail_shortcuts(safe_nodes)

            # B. Fact Extractor Pipeline (Run for all safe nodes to build full intelligence profile)
            extracted_facts = self._extract_facts_selectively(safe_nodes, predictions)

            # C. Post Security Validator Engine (Now seamlessly receives real predictions/facts)
            post_sec_results = self.post_security_pipeline.predict(
                safe_nodes, predictions, extracted_facts, historical_context
            )

            # Map subset inference matrix results securely back to original batch positions
            for safe_idx, original_idx in enumerate(safe_indices):
                final_classifications[original_idx] = predictions[safe_idx]
                final_facts[original_idx] = extracted_facts[safe_idx]

                # Enrich Post Security with Pass 1 contextual stats safely here if desired
                p2_result = post_sec_results[safe_idx]
                if not p2_result.get("context_records_evaluated"):
                    p2_result["context_records_evaluated"] = len(historical_context) if historical_context else 0

                p1_pred = pre_sec_predictions[original_idx]
                p2_result["pre_security_passed"] = p1_pred.get("pre_security_passed")
                p2_result["security_risks"] = p1_pred.get("security_risks")
                p2_result["extracted_spam_score"] = p1_pred.get("extracted_spam_score")
                p2_result["has_reply_to_mismatch"] = p1_pred.get("has_reply_to_mismatch")
                p2_result["is_possible_prompt_injection"] = p1_pred.get("is_possible_prompt_injection")
                p2_result["raw_spf_result"] = p1_pred.get("raw_spf_result")
                p2_result["raw_dkim_result"] = p1_pred.get("raw_dkim_result")

                final_security[original_idx] = p2_result

        # Handle items that failed Pass 1 Pre-Security Rules (Forced Quarantine Mapping)
        for idx, pred in enumerate(pre_sec_predictions):
            if not pred["pre_security_passed"]:
                self._apply_quarantine_fallback(
                    idx=idx,
                    pred=pred,
                    statuses=statuses,
                    final_classifications=final_classifications,
                    final_facts=final_facts,
                    final_security=final_security
                )

        # 4. Columnar Matrix Zip (Assembles the combined multi-table DB payloads cleanly)
        return [
            {
                "id": email_nodes[i].get("id"),
                "status": statuses[i],
                "cleaned_body": email_nodes[i].get("cleaned_body"),
                "classification": final_classifications[i],
                "actions": final_facts[i],  # Keep key as 'actions' to match downstream workers / HTTP responses
                "security": final_security[i]
            }
            for i in range(len(email_nodes))
        ]

    def _predict_intent_with_gmail_shortcuts(self, safe_nodes: list[dict]) -> list[Any]:
        from app.schemas.email_classification import EmailClassificationPrediction

        predictions = []
        to_classify_indices = []
        to_classify_nodes = []

        for idx, node in enumerate(safe_nodes):
            payload = node.get("raw_payload") or {}
            label_ids = payload.get("labelIds") or []

            # Check if Gmail flagged it as Promotions, Social, Forums, or SPAM
            is_noise = False
            for lid in label_ids:
                if lid in {
                    "CATEGORY_PROMOTIONS", "CATEGORY_PROMOTION",
                    "CATEGORY_SOCIAL", "CATEGORY_FORUMS", "CATEGORY_FORUM",
                    "SPAM", "CATEGORY_SPAM"
                }:
                    is_noise = True
                    break

            if is_noise:
                prediction = EmailClassificationPrediction(
                    label_id=1,  # others index
                    label="others",
                    confidence=1.0,
                    probabilities={
                        "financial": 0.0,
                        "others": 1.0,
                        "system_automated": 0.0,
                        "work_professional": 0.0
                    }
                )
                predictions.append(prediction)
            else:
                to_classify_indices.append(idx)
                to_classify_nodes.append(node)
                predictions.append(None)

        if to_classify_nodes:
            model_preds = self.classifier_engine.predict(to_classify_nodes)
            for m_idx, original_idx in enumerate(to_classify_indices):
                predictions[original_idx] = model_preds[m_idx]

        return predictions

    def _extract_facts_selectively(
            self,
            safe_nodes: list[dict],
            predictions: list[Any]
    ) -> list[EmailFactBatchResponse]:
        """
        Runs FactExtractor on safe nodes. If we want selective checks, we can filter,
        but for facts we extract them on all safe nodes.
        """
        # Run FactExtractor pipeline on all safe nodes
        return self.fact_extractor_pipeline.predict(safe_nodes)


    def _apply_quarantine_fallback(
            self,
            idx: int,
            pred: Any,
            statuses: list[str],
            final_classifications: list[Any],
            final_facts: list[Any],
            final_security: list[Any]
    ) -> None:
        """
        Mutates the columnar matrix tracking arrays at index `idx` to apply
        a unified quarantine state when Pass 1 Pre-Security checks fail.
        """
        statuses[idx] = "QUARANTINED_PRE_SECURITY"

        # 1. Matches EmailClassificationPrediction schema output
        final_classifications[idx] = {
            "label_id": -1,  # Using an explicit boundary ID for unsafe items
            "label": "spam",  # Falling back safely to spam bucket
            "confidence": 1.0,
            "probabilities": {}
        }

        # 2. FIXED FORMAT: Matches EmailFactBatchResponse schema layout
        final_facts[idx] = {
            "email_id": None,
            "facts": []
        }

        # 3. Matches PostSecurityValidator response contract shapes
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


    async def persist_ml_outputs(
            self,
            db_client,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Orchestrates all ML persistence operations.
        """
        await asyncio.gather(
            self._persist_email_metadata_and_category(db_client, email_records, ml_batch_outputs),
            self._persist_email_facts(db_client, email_records, ml_batch_outputs)
        )

    async def _persist_email_metadata_and_category(
            self,
            db_client,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Persists classification category and structured ai_metadata directly to emails table.
        """
        if not email_records or not ml_batch_outputs:
            return

        async def _update_single_email(email_id: str, category_name: str, metadata: dict):
            try:
                db_client.table("emails").update({
                    "category": category_name,
                    "ai_metadata": metadata
                }).eq("id", email_id).execute()
            except Exception as e:
                print(f"[ML ERROR] Failed to update email {email_id} category/metadata: {str(e)}")

        update_tasks = []
        for email, ml in zip(email_records, ml_batch_outputs):
            classification = ml.get("classification", {})
            security = ml.get("security", {})
            status = ml.get("status", "APPROVED")

            label_name = classification.get("label")
            label_id = classification.get("label_id")

            # Fallback block just in case something comes up completely blank
            if label_id is None:
                print(f"[ML WARNING] Missing label_id for email {email['id']}. Applying defaults.")
                label_id = -1
                label_name = label_name or "UNCATEGORIZED"

            # Check if this email went to quarantine / failed pre-security
            is_quarantined = (status == "QUARANTINED_PRE_SECURITY")

            # Build structured ai_metadata
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
                _update_single_email(email["id"], label_name, ai_metadata)
            )

        if update_tasks:
            await asyncio.gather(*update_tasks)
            print(f"[ML SUCCESS] Processed category and metadata for {len(update_tasks)} emails")


    async def _persist_email_facts(
        self,
        db_client,
        email_records: list[dict],
        ml_batch_outputs: list[dict]
    ):
        """
        Persists NLP fact extraction outputs into email_facts table.
        One email → multiple fact rows.
        """
        if not email_records or not ml_batch_outputs:
            return

        fact_rows = []
        for email, ml in zip(email_records, ml_batch_outputs):
            if not isinstance(ml, dict):
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
            anchor_date = self._safe_parse_datetime(email.get("received_at"))

            for fact in fact_items:
                if not isinstance(fact, dict):
                    print(
                        f"[ML WARNING] Skipping malformed fact item: {fact}")
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
            db_client.table("email_facts").insert(
                fact_rows
            ).execute()

            print(f"[ML SUCCESS] Stored {len(fact_rows)} email facts")

        except Exception as e:
            print(f"[ML ERROR] Email facts insert failed: {str(e)}")


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


    def _html_to_text(self, html: str) -> str:
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        cleaned_text = soup.get_text(separator=" ")

        return cleaned_text