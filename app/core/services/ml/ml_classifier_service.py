from typing import Any
from app.core.ml_models.classifier.predictor import EmailClassifier
from app.schemas.email_classification import EmailClassificationPrediction
from app.core.ml_models.unified_constants import (
    GMAIL_NOISE_LABELS,
    DEFAULT_INTENT_LABEL_ID,
    DEFAULT_INTENT_LABEL
)


class MLClassifierService:
    def __init__(self):
        self.classifier_engine = EmailClassifier()

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
