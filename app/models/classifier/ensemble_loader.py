import torch
from pathlib import Path
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    PreTrainedTokenizer
)
from typing import Dict, Optional, List

from app.core.schemas.email_classifications import EmailClassificationPrediction

ARTIFACTS = [
    ("best_model_fold_1_best", 1),
    ("best_model_fold_4_better", 1),
    ("best_model_fold_3_stable", 1),
]

LABELS = {
    0: "content_subscription",
    1: "financial",
    2: "personal",
    3: "promotional",
    4: "spam",
    5: "system_automated",
    6: "work_professional"
}

BASE_PATH = Path(__file__).parent
ARTIFACTS_DIR = BASE_PATH / "artifacts"


class EnsembleEmailClassifier:
    def __init__(self):
        self.models: list[torch.nn.Module] = []
        self.weights: list[int] = []
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        first_model_dir = ARTIFACTS_DIR / ARTIFACTS[0][0]
        tokenizer: Optional[PreTrainedTokenizer] = AutoTokenizer.from_pretrained(str(first_model_dir))
        if tokenizer is None:
            raise RuntimeError(f"Failed to load tokenizer from {first_model_dir}")
        self.tokenizer: PreTrainedTokenizer = tokenizer
        self.labels: Dict[int, str] = LABELS.copy()
        for folder, weight in ARTIFACTS:
            model_dir = ARTIFACTS_DIR / folder
            model: torch.nn.Module = AutoModelForSequenceClassification.from_pretrained(
                str(model_dir)
            )
            if not self.models:
                # Prefer model-provided labels when available.
                id2label = getattr(model.config, "id2label", None)
                if id2label:
                    self.labels = {int(k): str(v) for k, v in id2label.items()}
            model.to(self.device)
            model.eval()
            self.models.append(model)
            self.weights.append(weight)

    def predict(self, email_texts: List[str]) -> List[EmailClassificationPrediction]:
        if self.tokenizer is None:
            raise RuntimeError("Tokenizer is not loaded.")
        if not email_texts:
            return []
        inputs = self.tokenizer(
            email_texts,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=512
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        all_probs = []
        for model, weight in zip(self.models, self.weights):
            with torch.inference_mode():
                outputs = model(**inputs)
                probs = torch.softmax(outputs.logits, dim=1)
                all_probs.append(probs * weight)
        weighted_probs = torch.stack(all_probs).sum(dim=0)
        weighted_probs /= sum(self.weights)
        final_preds = torch.argmax(weighted_probs, dim=1).tolist()
        confidences = torch.max(weighted_probs, dim=1).values.tolist()
        probabilities = weighted_probs.tolist()
        results: List[EmailClassificationPrediction] = []
        for pred, conf, probs in zip(final_preds, confidences, probabilities):
            label_id = int(pred)
            probability_map = {
                self.labels.get(i, str(i)): float(prob)
                for i, prob in enumerate(probs)
            }
            results.append(
                EmailClassificationPrediction(
                    label_id=label_id,
                    label=self.labels.get(label_id, str(label_id)),
                    confidence=round(float(conf), 4),
                    probabilities=probability_map
                )
            )
        return results
