# app/models/security/post_security.py
from typing import List, Dict, Any
from app.models.unified_constants import (
    INTENT_MANIFEST,
    ACTION_SECURITY_MANIFEST,
    SECURITY_TRUST_LEVELS,
    SECURITY_RISK_CATEGORIES
)


# Structuring your expected input/output classes for Pass 2c
class PostSecurityValidator:
    def __init__(self):
        print("[POST-SECURITY] Initializing Pass 2 Machine Learning Behavior Core...")

    def predict(
            self,
            safe_nodes: list[dict],
            classifications: list[Any],  # List[EmailClassificationPrediction]
            actions: list[dict],  # List[ExtractedActionBatchResponse dicts]
            historical_context: list[dict] = None
    ) -> list[dict]:
        """
        Executes Pass 2 deep behavioral context evaluation over safe data chunks.
        Combines (Classifier + Actions) first to isolate structural threats,
        then evaluates historical profiles to detect anomalies.
        """
        batch_predictions: list[dict] = []
        context_pool = historical_context if historical_context else []

        for idx, node in enumerate(safe_nodes):
            # Read metadata safely from prior layers using standard contract
            classification_obj = classifications[idx]
            action_envelope = actions[idx]

            # Resolve classifier index safely; default to index 6 (work_professional) if missing
            category_idx = classification_obj.category_index if classification_obj else 6

            # Extract configuration parameters dynamically from your locked INTENT_MANIFEST
            intent_config = INTENT_MANIFEST.get(category_idx, {"penalty_score": 0.1, "is_high_risk": False})
            base_penalty = intent_config["penalty_score"]
            is_high_risk_intent = intent_config["is_high_risk"]

            # Unpack the pure list of action items extracted from the email body text
            action_items = action_envelope.get("actions", [])

            # Dynamic arrays updated by downstream placeholder verification loops
            detected_risks: list[str] = []
            is_anomaly = False

            # =====================================================================
            # STEP A: COMBINE CLASSIFIER + ACTION EXTRACTOR (In-Message Evaluation)
            # =====================================================================
            has_structural_risk = self._evaluate_in_message_risk_profile(
                category_idx=category_idx,
                is_high_risk_intent=is_high_risk_intent,
                action_items=action_items,
                detected_risks=detected_risks
            )

            # =====================================================================
            # STEP B: INTEGRATE HISTORICAL USER CONTEXT (Behavioral Anomaly Check)
            # =====================================================================
            if has_structural_risk and context_pool:
                # Safely parse sender tracking parameters from the matrix pointers
                payload = node.get("raw_payload", {})
                headers = payload.get("headers", {})
                sender_address = headers.get("From", "").strip()

                is_anomaly = self._evaluate_historical_behavioral_shift(
                    sender=sender_address,
                    category_idx=category_idx,
                    action_items=action_items,
                    history=context_pool,
                    detected_risks=detected_risks
                )

            # =====================================================================
            # STEP C: SCORE CALCULATION & MATRIX ASSEMBLE
            # =====================================================================
            # Apply dynamic modifiers on top of baseline weights from manifest
            final_trust_score = base_penalty

            if is_anomaly:
                # Pull penalty dynamically out of your manifest modifiers
                anomaly_multiplier = ACTION_SECURITY_MANIFEST["multipliers"]["high_concern_anomaly_penalty"]
                final_trust_score = round(base_penalty * anomaly_multiplier, 2)

            # Resolve flat system level matching your exact manifest dictionary strings
            if is_anomaly:
                trust_level = "suspicious"  # Directly matches SECURITY_TRUST_LEVELS[3]
            elif final_trust_score <= 0.2:
                trust_level = "trusted"  # Directly matches SECURITY_TRUST_LEVELS[1]
            else:
                trust_level = "neutral"  # Directly matches SECURITY_TRUST_LEVELS[2]

            batch_predictions.append({
                "security_trust_score": final_trust_score,
                "security_trust_level": trust_level,
                "is_phishing_anomaly": is_anomaly,
                "risks_detected": detected_risks,
                "context_records_evaluated": len(context_pool)
            })

        return batch_predictions

    def _evaluate_in_message_risk_profile(
            self, category_idx: int, is_high_risk_intent: bool, action_items: list[dict], detected_risks: list[str]
    ) -> bool:
        """
        Stage 1: Checks for multi-model risks by identifying if a highly targeted
        intent matches suspicious actions inside the current message text.
        """
        # Read standard linguistic arrays from manifest
        high_concern_verbs = ACTION_SECURITY_MANIFEST["high_concern_verbs"]
        high_risk_verbs = ACTION_SECURITY_MANIFEST["high_risk_verbs"]

        # Loop over verbs extracted from your upstream action model
        for action in action_items:
            verb = action.get("verb_primitive", "").lower()

            # Intersection 1: Financial Label + Sensitive Request Actions
            if category_idx == 1 and (verb in high_concern_verbs):
                # Map using the exact manifest strings
                detected_risks.append(SECURITY_RISK_CATEGORIES[1])  # "financial_anomaly"
                return True

            # Intersection 2: Promotional Label + High Concern Verification Link Requests
            if category_idx == 3 and (verb in high_concern_verbs):
                detected_risks.append(SECURITY_RISK_CATEGORIES[2])  # "marketing_phish_vector"
                return True

            # Intersection 3: Automated/System Alerts + Destructive Action Tasks
            if category_idx == 5 and (verb in high_risk_verbs):
                detected_risks.append(SECURITY_RISK_CATEGORIES[4])  # "spoofing_target"
                return True

        # Fallback check for structural isolation
        if is_high_risk_intent and len(action_items) > 0:
            return True

        return False

    def _evaluate_historical_behavioral_shift(
            self, sender: str, category_idx: int, action_items: list[dict], history: list[dict],
            detected_risks: list[str]
    ) -> bool:
        """
        Stage 2: Compares isolated structural risks against historical communication
        baselines to verify if this behavior deviates from past patterns.
        """
        # Placeholder wrapper block for upcoming contextual comparisons
        # Returns True if current behavior represents a dangerous behavioral shift
        return False