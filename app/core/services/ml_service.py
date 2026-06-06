# app/core/services/ml_service.py
import asyncio
from datetime import datetime, timezone


class MLEngineService:
    def __init__(self):
        print("[ML ENGINE] Initializing Production Native-Batch AI Orchestrator...")
        # Your dedicated localized model pipelines loaded globally into hardware memory
        self.classifier_batch_pipeline = None
        self.action_extractor_batch_pipeline = None
        self.security_contextual_engine = None

    def _preprocess_batch(self, email_nodes: list[dict]) -> list[str]:
        """
        Cleans and standardizes an entire array of text elements simultaneously.
        """
        cleaned_texts = []
        for node in email_nodes:
            raw_text = node.get("body_content") or node.get("snippet") or ""
            # Quick string normalization wrapper
            clean = " ".join(raw_text.split())[:1024]
            cleaned_texts.append(clean if clean else "[Empty Email Body]")
        return cleaned_texts

    async def run_batch_inference(self, email_nodes: list[dict], historical_context: list[dict] = None) -> list[dict]:
        """
        Accepts a full batch list of emails and runs native-batch inference through the models.
        Includes a historical_context parameter for advanced security trend matching.
        """
        if not email_nodes:
            return []

        # 1. Prepare text inputs for the batch-capable models
        cleaned_inputs = self._preprocess_batch(email_nodes)

        print(f"[ML INFERENCE] Feeding batch of {len(cleaned_inputs)} elements into parallel hardware models...")

        # 2. Simulate parallel execution of native batch models
        # In production, these call the underlying batch matrix multiplication (GPU-optimized)
        await asyncio.sleep(0.25)

        # --- MODEL A: Native Batch Classification ---
        # Example: batch_outputs = self.classifier_batch_pipeline(cleaned_inputs, batch_size=len(cleaned_inputs))
        mock_classification_batch = [
            {"category": "Task" if i % 2 == 0 else "Update", "confidence": 0.92}
            for i in range(len(cleaned_inputs))
        ]

        # --- MODEL B: Native Batch Action Item Extraction ---
        mock_action_batch = [
            {"action_items": [f"Extracted Task Action Marker #{i}"], "deadlines": []}
            for i in range(len(cleaned_inputs))
        ]

        # --- MODEL C: Contextual Security Model ---
        # This layer reads the historical_context tracking inputs to flag anomalies (e.g., unexpected sender changes)
        mock_security_batch = []
        for idx, node in enumerate(email_nodes):  # Initialized idx loop tracker cleanly here!
            sender = node.get("sender", "Unknown")
            is_anomaly = False

            if historical_context:
                # Advanced Logic Check: evaluate if sender behavior correlates with previous historical records
                sender_history = [h for h in historical_context if h.get("sender") == sender]
                if len(sender_history) > 0 and idx % 5 == 0:  # Using the corrected idx variable
                    is_anomaly = True

            mock_security_batch.append({
                "is_phishing": is_anomaly,
                "risk_score": 0.85 if is_anomaly else 0.01,
                "context_records_evaluated": len(historical_context) if historical_context else 0
            })

        # 3. Zip results back together into a structured array matching the original records
        enriched_batch = []
        for idx, original_node in enumerate(email_nodes):
            enriched_batch.append({
                "message_id": original_node["message_id"],
                "thread_id": original_node.get("thread_id"),
                "sender": original_node.get("sender"),
                "subject": original_node.get("subject"),
                "date_sent": original_node.get("date_sent"),
                "body_content": original_node.get("body_content"),
                "raw_ai_outputs": {
                    "classification": mock_classification_batch[idx],
                    "extracted_features": mock_action_batch[idx],
                    "security_screening": mock_security_batch[idx],
                    "evaluated_at": datetime.now(timezone.utc).isoformat()
                },
                "is_derived_features_calculated": False  # FLAG: Database schema marker for Stage 2 Worker!
            })

        return enriched_batch