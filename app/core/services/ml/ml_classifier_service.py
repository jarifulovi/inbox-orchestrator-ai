from typing import Any
from app.core.ml_models.classifier.predictor import EmailClassifier
from app.core.schemas.email_classifications import EmailClassificationPrediction
from app.core.ml_models.unified_constants import (
    GMAIL_NOISE_LABELS,
    DEFAULT_INTENT_LABEL_ID,
    DEFAULT_INTENT_LABEL
)


class MLClassifierService:
    # Rule set definitions for automated system update noise identification
    AUTOMATED_SENDER_PATTERNS = {
        "no-reply@", "noreply@", "do-not-reply@", "donotreply@",
        "notifications@", "notification@", "alert@", "alerts@",
        "updates@", "info@", "mailer-daemon@", "system@",
        "auto-confirm@", "service@", "support-noreply@"
    }

    AUTOMATED_DOMAINS = {
        "accounts.google.com", "google.com",
        "accountprotection.microsoft.com", "microsoft.com",
        "github.com", "aws.amazon.com", "amazon.com",
        "linkedin.com", "slack.com", "atlassian.com",
        "stripe.com", "vercel.com", "cloudflare.com",
        "notion.so", "figma.com", "gitlab.com", "docker.com"
    }

    # Tier 1: Routine Informational System Noise -> Reclassified to 'others' (bypasses LLM)
    ROUTINE_NOISE_KEYWORDS = [
        "verification code", "one-time password", "otp", "login attempt",
        "new sign-in", "password reset", "two-factor", "2-step verification",
        "terms of service", "privacy policy update", "weekly digest",
        "monthly digest", "activity report", "deployment succeeded",
        "confirm your email", "security alert"
    ]

    # Tier 2: Actionable System Notifications -> Reclassified / kept as 'system_automated' (sent to LLM)
    ACTIONABLE_SYSTEM_KEYWORDS = [
        "action required", "payment failed", "invoice past due", "past due",
        "build failed", "deployment failed", "quota exceeded", "storage full",
        "domain expiring", "expiring soon", "critical alert", "security vulnerability",
        "unauthorized access", "service disruption"
    ]

    def __init__(self):
        self._classifier_engine = None

    @property
    def classifier_engine(self) -> EmailClassifier:
        if self._classifier_engine is None:
            self._classifier_engine = EmailClassifier()
        return self._classifier_engine

    def predict_intent_with_gmail_shortcuts(self, safe_nodes: list[dict]) -> list[Any]:
        """
        Predicts intent categories for safe email nodes, bypassing classifier model
        for obvious Gmail noise labels (Promotions, Social, Forums, SPAM).
        """
        predictions = []
        to_classify_indices = []
        to_classify_nodes = []

        for idx, node in enumerate(safe_nodes):
            payload = node.get("raw_payload") or {}
            label_ids = payload.get("labelIds") or []

            # Check if Gmail flagged it as Promotions, Social, Forums, or SPAM
            is_noise = any(lid in GMAIL_NOISE_LABELS for lid in label_ids)

            if is_noise:
                prediction = EmailClassificationPrediction(
                    label_id=DEFAULT_INTENT_LABEL_ID,
                    label=DEFAULT_INTENT_LABEL,
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

    def apply_update_noise_rules(self, safe_nodes: list[dict], predictions: list[Any]) -> list[Any]:
        """
        Applies two-tier rule-based post-filtering for automated system/update noise:
        1. Pure routine informational noise (OTPs, login alerts, terms updates) -> reclassified to 'others' (ID: 1)
           so they completely bypass LLM feature generation and save token cost.
        2. Critical actionable system notifications ('Action Required', 'Payment Failed', 'Build Failed') -> reclassified/kept
           as 'system_automated' (ID: 2) so they feed to LLM to generate urgent user tasks.
        """
        if not safe_nodes or not predictions:
            return predictions

        refined_predictions = []

        for node, pred in zip(safe_nodes, predictions):
            if pred is None:
                refined_predictions.append(pred)
                continue

            sender = str(node.get("sender") or "").lower()
            subject = str(node.get("subject") or "").lower()

            is_automated_sender = any(pattern in sender for pattern in self.AUTOMATED_SENDER_PATTERNS)
            is_automated_domain = any(domain in sender for domain in self.AUTOMATED_DOMAINS)
            is_automated_source = is_automated_sender or is_automated_domain

            # Check for Tier 2: Actionable System Keywords
            is_actionable_system = any(kw in subject for kw in self.ACTIONABLE_SYSTEM_KEYWORDS)

            # Check for Tier 1: Routine Noise Keywords
            is_routine_noise = any(kw in subject for kw in self.ROUTINE_NOISE_KEYWORDS)

            curr_label = pred.get("label") if isinstance(pred, dict) else getattr(pred, "label", None)

            # --- TIER 2 OVERRIDE: Actionable System Alert -> system_automated (feeds LLM) ---
            if is_actionable_system or (is_automated_source and any(kw in subject for kw in ["action required", "urgent", "failed", "error", "expired"])):
                if curr_label != "system_automated":
                    override_pred = EmailClassificationPrediction(
                        label_id=2,  # system_automated
                        label="system_automated",
                        confidence=0.95,
                        probabilities={
                            "financial": 0.0,
                            "others": 0.05,
                            "system_automated": 0.95,
                            "work_professional": 0.0
                        }
                    )
                    refined_predictions.append(override_pred)
                    continue

            # --- TIER 1 OVERRIDE: Routine System Noise -> 'others' (bypasses LLM) ---
            if (is_automated_source and (is_routine_noise or not is_actionable_system)) or is_routine_noise:
                if curr_label in ("work_professional", "financial", "system_automated"):
                    override_pred = EmailClassificationPrediction(
                        label_id=DEFAULT_INTENT_LABEL_ID,  # 1 (others)
                        label=DEFAULT_INTENT_LABEL,        # "others"
                        confidence=0.95,
                        probabilities={
                            "financial": 0.0,
                            "others": 0.95,
                            "system_automated": 0.05,
                            "work_professional": 0.0
                        }
                    )
                    refined_predictions.append(override_pred)
                    continue

            refined_predictions.append(pred)

        return refined_predictions
