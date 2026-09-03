import torch
from pathlib import Path
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    PreTrainedTokenizer
)
from typing import Dict, Optional, List

from app.core.schemas.email_classifications import EmailClassificationPrediction

BEST_MODEL_FOLDER = "best_model_fold_2_best"

LABELS = {
    0: "financial",
    1: "others",
    2: "system_automated",
    3: "work_professional"
}

BASE_PATH = Path(__file__).parent
ARTIFACTS_DIR = BASE_PATH / "artifacts"


class EnsembleEmailClassifier:
    def __init__(self):
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        model_dir = ARTIFACTS_DIR / BEST_MODEL_FOLDER
        print(f"[EmailClassifier] Loading single optimized classifier model: {BEST_MODEL_FOLDER}")

        tokenizer: Optional[PreTrainedTokenizer] = AutoTokenizer.from_pretrained(str(model_dir))
        if tokenizer is None:
            raise RuntimeError(f"Failed to load tokenizer from {model_dir}")
        self.tokenizer: PreTrainedTokenizer = tokenizer

        self.model: torch.nn.Module = AutoModelForSequenceClassification.from_pretrained(
            str(model_dir)
        )
        self.labels: Dict[int, str] = LABELS.copy()
        id2label = getattr(self.model.config, "id2label", None)
        if id2label:
            self.labels = {int(k): str(v) for k, v in id2label.items()}

        self.model.to(self.device)
        self.model.eval()

    def predict(self, email_texts: List[str]) -> List[EmailClassificationPrediction]:
        if self.tokenizer is None or self.model is None:
            raise RuntimeError("Classifier model/tokenizer is not loaded.")
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

        with torch.inference_mode():
            outputs = self.model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1)

        final_preds = torch.argmax(probs, dim=1).tolist()
        confidences = torch.max(probs, dim=1).values.tolist()
        probabilities = probs.tolist()

        results: List[EmailClassificationPrediction] = []
        for pred, conf, probs_list in zip(final_preds, confidences, probabilities):
            label_id = int(pred)
            probability_map = {
                self.labels.get(i, str(i)): float(p)
                for i, p in enumerate(probs_list)
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
