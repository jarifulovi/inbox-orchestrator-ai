import json
import unittest
from pathlib import Path

from app.core.ml_models.classifier.model_loader import ClassifierModelLoader, LABELS
from app.core.ml_models.classifier.predictor import EmailClassifier
from app.core.services.ml.ml_classifier_service import MLClassifierService


class ClassifierUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_file_path = Path(__file__).parent / "files" / "classifier_test_data.json"
        with open(test_file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            cls.test_cases = data.get("test_cases", [])

        cls.classifier = EmailClassifier()
        cls.service = MLClassifierService()

    def test_classifier_labels_mapping(self):
        """Verify the 4 core classification categories and integer IDs."""
        expected_labels = {
            0: "financial",
            1: "others",
            2: "system_automated",
            3: "work_professional"
        }
        self.assertEqual(LABELS, expected_labels)

        model_loader = ClassifierModelLoader()
        self.assertIsNotNone(model_loader.labels)
        for label_id, label_name in expected_labels.items():
            self.assertIn(label_name, model_loader.labels.values())

    def test_classifier_empty_input(self):
        """Verify that passing empty input returns an empty list without crashing."""
        results = self.classifier.predict([])
        self.assertEqual(results, [])

    def test_classifier_batch_prediction(self):
        """Batch predict emails from test data file and validate classification schemas."""
        safe_nodes = [
            {
                "subject": tc["subject"],
                "cleaned_body": tc["cleaned_body"]
            }
            for tc in self.test_cases
        ]

        results = self.classifier.predict(safe_nodes)
        self.assertEqual(len(results), len(self.test_cases))

        valid_labels = {"financial", "others", "system_automated", "work_professional"}

        for idx, res in enumerate(results):
            tc = self.test_cases[idx]
            self.assertIn("label", res)
            self.assertIn("label_id", res)
            self.assertIn("confidence", res)
            self.assertIn("probabilities", res)

            self.assertIn(res["label"], valid_labels)
            self.assertIsInstance(res["label_id"], int)
            self.assertIsInstance(res["confidence"], float)
            self.assertGreaterEqual(res["confidence"], 0.0)
            self.assertLessEqual(res["confidence"], 1.0)

            # Check probability keys
            probs = res["probabilities"]
            for label_name in valid_labels:
                self.assertIn(label_name, probs)

    def test_ml_classifier_service_shortcuts(self):
        """Verify noise shortcuts in MLClassifierService for Gmail noise labels."""
        noise_node = {
            "subject": "50% off summer sale",
            "cleaned_body": "Shop now for exclusive deals.",
            "raw_payload": {"labelIds": ["CATEGORY_PROMOTIONS"]}
        }
        preds = self.service.predict_intent_with_gmail_shortcuts([noise_node])
        self.assertEqual(len(preds), 1)
        pred = preds[0]

        label = pred["label"] if isinstance(pred, dict) else getattr(pred, "label", None)
        confidence = pred["confidence"] if isinstance(pred, dict) else getattr(pred, "confidence", None)

        self.assertEqual(label, "others")
        self.assertEqual(confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
