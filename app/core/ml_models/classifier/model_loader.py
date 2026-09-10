try:
    import torch
    from transformers import (
        AutoTokenizer,
        AutoModelForSequenceClassification,
        PreTrainedTokenizer
    )
except ImportError:
    torch = None
    AutoTokenizer = None
    AutoModelForSequenceClassification = None
    PreTrainedTokenizer = None
from pathlib import Path
from typing import Dict, List, Optional

from app.core.schemas.email_classifications import EmailClassificationPrediction
from app.core.services.utils.memory_utils import force_garbage_collection, apply_thread_limits

apply_thread_limits()

BEST_MODEL_FOLDER = "best_model_fold_2_best"

LABELS = {
    0: "financial",
    1: "others",
    2: "system_automated",
    3: "work_professional"
}

BASE_PATH = Path(__file__).parent
ARTIFACTS_DIR = BASE_PATH / "artifacts"


class ClassifierModelLoader:
    def __init__(self):
        self.device = None
        self.tokenizer = None
        self.model = None
        self.labels: Dict[int, str] = LABELS.copy()

        if torch is None or AutoTokenizer is None or AutoModelForSequenceClassification is None:
            print("[EmailClassifier] PyTorch/Transformers not installed. Operating in lightweight fallback mode.")
            return

        try:
            try:
                torch.set_num_threads(2)
            except Exception:
                pass

            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model_dir = ARTIFACTS_DIR / BEST_MODEL_FOLDER
            print(f"[EmailClassifier] Loading PyTorch classifier model from: {model_dir}")

            if not model_dir.exists():
                print(f"[EmailClassifier] Local model directory not found: '{model_dir}'. Operating in lightweight fallback mode.")
                return

            model_dir_str = str(model_dir.resolve())

            try:
                tokenizer = AutoTokenizer.from_pretrained(model_dir_str, local_files_only=True)
            except Exception:
                tokenizer = AutoTokenizer.from_pretrained(model_dir_str)

            if tokenizer is None:
                print(f"[EmailClassifier] Failed to load tokenizer from {model_dir}. Operating in fallback mode.")
                return
            self.tokenizer = tokenizer

            try:
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    model_dir_str,
                    local_files_only=True
                )
            except Exception:
                self.model = AutoModelForSequenceClassification.from_pretrained(model_dir_str)

            id2label = getattr(self.model.config, "id2label", None)
            if id2label:
                self.labels = {int(k): str(v) for k, v in id2label.items()}

            self.model.to(self.device)
            self.model.eval()
            force_garbage_collection()
        except Exception as e:
            print(f"[EmailClassifier] Exception during model load: {e}. Falling back to default classifier mode.")
            self.tokenizer = None
            self.model = None

    def predict(self, email_texts: List[str]) -> List[EmailClassificationPrediction]:
        if not email_texts:
            return []

        if self.tokenizer is None or self.model is None or torch is None:
            # Render / Lightweight fallback prediction
            fallback_map = {
                "financial": 0.0,
                "others": 1.0,
                "system_automated": 0.0,
                "work_professional": 0.0
            }
            return [
                EmailClassificationPrediction(
                    label_id=1,
                    label="others",
                    confidence=0.50,
                    probabilities=fallback_map
                )
                for _ in email_texts
            ]

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

        force_garbage_collection()
        return results

