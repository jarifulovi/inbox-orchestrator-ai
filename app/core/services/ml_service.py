# app/core/services/ml_service.py
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any
from bs4 import BeautifulSoup

# Real component engines
from app.models.classifier.predictor import EmailClassifier
from app.models.security.pre_security import PreSecurityFilter


class MLEngineService:
    def __init__(self):
        print("[ML ENGINE] Initializing Production Native-Batch AI Orchestrator...")
        self.pre_security_engine = PreSecurityFilter()  # Pass 1: Context-free safety filter
        self.classifier_engine = EmailClassifier()  # Pass 2a: Intent categorization

        # Pipelines yet to be finalized (kept as None / commented out structurally)
        self.action_extractor_pipeline = None  # Pass 2b: Action item extraction
        self.post_security_pipeline = None  # Pass 3: Post-Security context validator

    def _preprocess_batch(self, email_nodes: list[dict]) -> list[dict]:
        """
        Ingests the pre-parsed 'body' string, normalizes formatting/whitespace,
        and cuts it at a safe length to protect regex engines.
        """
        for node in email_nodes:
            # 1. Grab your pre-parsed schema body field directly
            raw_text = node.get("body") or node.get("snippet") or ""

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

    async def run_batch_inference(
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
        # Evaluates Body content + Subject via the injected raw_payload headers matrix
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
            # Build an explicit subset of safe dictionary nodes.
            # Downstream models now read node["id"] and node["cleaned_body"] cleanly from here.
            safe_nodes = [email_nodes[i] for i in safe_indices]

            # A. Core Intent Category Inference
            predictions = self.classifier_engine.predict(safe_nodes)

            # B. Placeholder for Action Extractor Pipeline (Commented inline for future replacement)
            # extracted_actions = self.action_extractor_pipeline.predict(safe_nodes)
            extracted_actions = [
                {"action_items": ["Extracted Task Marker"], "deadlines": []}
                for _ in range(len(safe_nodes))
            ]

            # C. Placeholder for Post Security Validator Engine (Pass 2 - Behavioral Deep Context)
            # post_sec_results = self.post_security_pipeline.predict(safe_nodes, predictions, extracted_actions, historical_context)
            post_sec_results = []
            for safe_idx, original_idx in enumerate(safe_indices):
                # Access metrics dynamically calculated by Pass 1 in memory using the original pointer
                p1_score = pre_sec_predictions[original_idx].pass1_computed_score
                p1_risks = pre_sec_predictions[original_idx].security_risks

                # Baseline scoring loop using Pass 1 metrics safely
                final_score = p1_score  # Contextual multipliers are injected here later
                level = "trusted" if final_score >= 0.80 else ("neutral" if final_score >= 0.40 else "suspicious")

                post_sec_results.append({
                    "security_trust_score": round(final_score, 2),
                    "security_trust_level": level,
                    "is_phishing_anomaly": False,
                    "risks_detected": p1_risks,
                    "context_records_evaluated": len(historical_context) if historical_context else 0
                })

            # Map subset inference matrix results securely back to original batch positions
            for safe_idx, original_idx in enumerate(safe_indices):
                final_classifications[original_idx] = predictions[safe_idx]
                final_actions[original_idx] = extracted_actions[safe_idx]
                final_security[original_idx] = post_sec_results[safe_idx]

        # Handle items that failed Pass 1 Pre-Security Rules (Forced Quarantine Mapping)
        for idx, pred in enumerate(pre_sec_predictions):
            if not pred.pre_security_passed:
                statuses[idx] = "QUARANTINED_PRE_SECURITY"
                final_classifications[idx] = {"category": "Unsafe / Injection", "confidence": 1.0}
                final_actions[idx] = {"action_items": [], "deadlines": []}
                final_security[idx] = {
                    "security_trust_score": pred.pass1_computed_score,  # Drops safely to 0.00
                    "security_trust_level": "suspicious",
                    "is_phishing_anomaly": True,
                    "risks_detected": pred.security_risks,
                    "context_records_evaluated": 0
                }

        # 4. Columnar Matrix Zip (Assembles the combined multi-table DB payloads cleanly)
        return [
            {
                "id": email_nodes[i].get("id"),
                "status": statuses[i],
                "classification": final_classifications[i],
                "actions": final_actions[i],
                "security": final_security[i]
            }
            for i in range(len(email_nodes))
        ]

    def _html_to_text(self, html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n")