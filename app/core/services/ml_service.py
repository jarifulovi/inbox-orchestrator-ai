# app/core/services/ml_service.py
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any
from bs4 import BeautifulSoup

from app.models.action_extractor.extractor import ActionExtractor
# Real component engines
from app.models.classifier.predictor import EmailClassifier
from app.models.security import PostSecurityValidator
from app.models.security.pre_security import PreSecurityFilter


class MLEngineService:
    def __init__(self):
        print("[ML ENGINE] Initializing Production Native-Batch AI Orchestrator...")
        self.pre_security_engine = PreSecurityFilter()  # Pass 1: Context-free safety filter
        self.classifier_engine = EmailClassifier()  # Pass 2a: Intent categorization
        self.action_extractor_pipeline = ActionExtractor()
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
            print("The raw input : ", raw_input[:100])
            print("The raw text : ", raw_text[:100])

            # 2. Standardize all line break formats and strip empty trailing gaps
            text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)

            # 3. Truncate at 50,000 characters to prevent backtracking regex freezes
            if len(text) > 50000:
                text = text[:50000].rsplit(" ", 1)[0]

            # 4. Bind the final string directly back to the matrix node
            node["cleaned_body"] = text if text else "[EMPTY_EMAIL]"
            print("The cleaned text : ", node["cleaned_body"][:100], "\n")

        return email_nodes

    def run_batch_inference(
            self,
            email_nodes: list[dict],
            historical_context: list[dict] = None
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
        safe_indices = [i for i, pred in enumerate(pre_sec_predictions) if pred.pre_security_passed]

        # Allocate empty tracking structures typed to Any to completely bypass IDE type-checker flags
        final_classifications: list[Any] = [None] * len(email_nodes)
        final_actions: list[Any] = [None] * len(email_nodes)
        final_security: list[Any] = [None] * len(email_nodes)
        statuses = ["APPROVED"] * len(email_nodes)

        # LAYER 2 & 3: CORE BATCHED INFERENCE (Only execute processing on safe data chunks)
        if safe_indices:
            safe_nodes = [email_nodes[i] for i in safe_indices]

            # A. Core Intent Category Inference
            predictions = self.classifier_engine.predict(safe_nodes)

            # B. Action Extractor Pipeline (Now officially wired up!)
            extracted_actions = self.action_extractor_pipeline.predict(safe_nodes)

            # C. Post Security Validator Engine (Now seamlessly receives real predictions/actions)
            post_sec_results = self.post_security_pipeline.predict(
                safe_nodes, predictions, extracted_actions, historical_context
            )

            # Map subset inference matrix results securely back to original batch positions
            for safe_idx, original_idx in enumerate(safe_indices):
                final_classifications[original_idx] = predictions[safe_idx]
                final_actions[original_idx] = extracted_actions[safe_idx]

                # Enrich Post Security with Pass 1 contextual stats safely here if desired
                p2_result = post_sec_results[safe_idx]
                if not p2_result.get("context_records_evaluated"):
                    p2_result["context_records_evaluated"] = len(historical_context) if historical_context else 0

                final_security[original_idx] = p2_result

        # Handle items that failed Pass 1 Pre-Security Rules (Forced Quarantine Mapping)
        for idx, pred in enumerate(pre_sec_predictions):
            if not pred.pre_security_passed:
                self._apply_quarantine_fallback(
                    idx=idx,
                    pred=pred,
                    statuses=statuses,
                    final_classifications=final_classifications,
                    final_actions=final_actions,
                    final_security=final_security
                )

        # 4. Columnar Matrix Zip (Assembles the combined multi-table DB payloads cleanly)
        return [
            {
                "id": email_nodes[i].get("id"),
                "status": statuses[i],
                "cleaned_body": email_nodes[i].get("cleaned_body"),
                "classification": final_classifications[i],
                "actions": final_actions[i],
                "security": final_security[i]
            }
            for i in range(len(email_nodes))
        ]

    def _apply_quarantine_fallback(
            self,
            idx: int,
            pred: Any,
            statuses: list[str],
            final_classifications: list[Any],
            final_actions: list[Any],
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

        # 2. FIXED FORMAT: Matches ExtractedActionBatchResponse schema layout
        final_actions[idx] = {
            "actions": []
        }

        # 3. Matches PostSecurityValidator response contract shapes
        final_security[idx] = {
            "security_trust_score": float(round(pred.pass1_computed_score, 2)) if hasattr(pred,
                                                                                          'pass1_computed_score') else 0.00,
            "security_trust_level": "suspicious",
            "is_phishing_anomaly": True,
            "risks_detected": pred.security_risks if hasattr(pred, 'security_risks') else ["PRE_SECURITY_VIOLATION"],
            "context_records_evaluated": 0
        }

    def _html_to_text(self, html: str) -> str:
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        cleaned_text = soup.get_text(separator=" ")

        return cleaned_text