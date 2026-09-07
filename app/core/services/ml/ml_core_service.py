import asyncio
from typing import Any
from app.core.services.ml.ml_pre_security_service import MLPreSecurityService
from app.core.services.ml.ml_classifier_service import MLClassifierService
from app.core.services.ml.ml_fact_service import MLFactService
from app.core.services.ml.ml_post_security_service import MLPostSecurityService
from app.core.services.utils.memory_utils import force_garbage_collection


class MLCoreService:
    """
    Main entry point / orchestrating service for ML inference and persistence pipeline.
    Coordinates Pre-Security, Intent Classification, Fact Extraction, and Post-Security validation.
    """
    def __init__(self):
        print("[ML CORE SERVICE] Initializing Production Native-Batch AI Orchestrator...")
        self.pre_sec_service = MLPreSecurityService()
        self.classifier_service = MLClassifierService()
        self.fact_service = MLFactService()
        self.post_sec_service = MLPostSecurityService()

    def run_batch_inference(
            self,
            email_nodes: list[dict],
            historical_context: list[dict] | None = None
    ) -> list[dict]:
        if not email_nodes:
            return []

        # 1. Clean Text inline directly inside the nodes matrix
        self.pre_sec_service.preprocess_batch(email_nodes)

        print(f"[ML INFERENCE] Initiating True Columnar Batch Execution for {len(email_nodes)} emails...")

        # LAYER 1: BATCHED PRE-SECURITY EVALUATION (Pass 1 - Context-Free)
        pre_sec_predictions = self.pre_sec_service.evaluate_pre_security(email_nodes)

        # Isolate clean index positions that are safe to process vs those quarantined
        safe_indices = [i for i, pred in enumerate(pre_sec_predictions) if pred["pre_security_passed"]]

        final_classifications: list[Any] = [None] * len(email_nodes)
        final_facts: list[Any] = [None] * len(email_nodes)
        final_security: list[Any] = [None] * len(email_nodes)
        statuses = ["APPROVED"] * len(email_nodes)

        # LAYER 2 & 3: CORE BATCHED INFERENCE (Only execute processing on safe data chunks)
        if safe_indices:
            safe_nodes = [email_nodes[i] for i in safe_indices]

            # A. Core Intent Category Inference
            predictions = self.classifier_service.predict_intent_with_gmail_shortcuts(safe_nodes)
            predictions = self.classifier_service.apply_update_noise_rules(safe_nodes, predictions)

            # B. Fact Extractor Pipeline
            extracted_facts = self.fact_service.extract_facts_selectively(safe_nodes, predictions)

            # C. Post Security Validator Engine
            post_sec_results = self.post_sec_service.evaluate_post_security(
                safe_nodes, predictions, extracted_facts, historical_context
            )

            # Map subset inference matrix results securely back to original batch positions
            for safe_idx, original_idx in enumerate(safe_indices):
                final_classifications[original_idx] = predictions[safe_idx]
                final_facts[original_idx] = extracted_facts[safe_idx]

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
                self.post_sec_service.apply_quarantine_fallback(
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
                "actions": final_facts[i],  # Keep key as 'actions' for downstream workers / HTTP responses
                "security": final_security[i]
            }
            for i in range(len(email_nodes))
        ]

    async def persist_ml_outputs(
            self,
            db_client,
            email_records: list[dict],
            ml_batch_outputs: list[dict]
    ):
        """
        Orchestrates all ML persistence operations across emails and email_facts tables.
        """
        await asyncio.gather(
            self.post_sec_service.persist_email_metadata_and_category(db_client, email_records, ml_batch_outputs),
            self.fact_service.persist_email_facts(db_client, email_records, ml_batch_outputs)
        )
        force_garbage_collection()
