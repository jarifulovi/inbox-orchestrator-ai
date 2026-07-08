import json
import unittest
from uuid import uuid4

from app.core.ml_models.fact_extractor.fact_extractor import FactExtractor


class FactExtractorIntegrationTests(unittest.TestCase):
    def setUp(self):
        with open("tests/files/fact_extractor_test_data.json", "r", encoding="utf-8") as fh:
            self.raw = json.load(fh)

        try:
            self.extractor = FactExtractor()
        except Exception as exc:
            raise unittest.SkipTest(
                "FactExtractor could not be instantiated (is 'en_core_web_sm' installed?)."
            ) from exc

    def test_overall_facts_classification_and_payload(self):
        minor_failures = []
        critical_failures = []

        for idx, entry in enumerate(self.raw):
            sentence = entry["sentence"]
            expected_type = entry["expected_type"]
            expected_payload = entry.get("expected_payload", {})

            # Prepare format for predictor
            mock_node = {
                "id": str(uuid4()),
                "cleaned_body": sentence
            }

            results = self.extractor.predict([mock_node])
            if not results or not results[0]["facts"]:
                critical_failures.append({
                    "sentence": sentence,
                    "error": "No facts extracted from the sentence."
                })
                continue

            # We retrieve the primary fact parsed from the single sentence
            predicted_fact = results[0]["facts"][0]
            predicted_type = predicted_fact["fact_type"]
            predicted_payload = predicted_fact.get("payload", {})

            # 1. Critical Check: Fact Type Matching
            if predicted_type != expected_type:
                critical_failures.append({
                    "sentence": sentence,
                    "expected_type": expected_type,
                    "predicted_type": predicted_type
                })
                continue

            # 2. Minor Check: Payload Attributes
            for key, expected_value in expected_payload.items():
                predicted_value = predicted_payload.get(key)

                # Normalize strings for comparison
                val_expected_str = str(expected_value).strip().lower() if expected_value is not None else ""
                val_predicted_str = str(predicted_value).strip().lower() if predicted_value is not None else ""

                if val_expected_str != val_predicted_str:
                    minor_failures.append({
                        "sentence": sentence,
                        "field": key,
                        "expected_value": expected_value,
                        "predicted_value": predicted_value
                    })

        # Report Critical Failures (Causes immediate test failure)
        if critical_failures:
            print("\n🚨 CRITICAL FAILURES (Type Mismatches):")
            for crit in critical_failures:
                print(f"- Sentence: \"{crit['sentence']}\"")
                if "error" in crit:
                    print(f"  Error: {crit['error']}")
                else:
                    print(f"  Expected Type: {crit['expected_type']}, Got: {crit['predicted_type']}")
            self.fail(f"Fact Extraction critical failures detected: {len(critical_failures)} type mismatches.")

        # Report Minor Failures (Does not fail the test suite, but logged as warnings)
        if minor_failures:
            print("\n⚠️ MINOR FAILURES (Payload Mismatches):")
            for minor in minor_failures:
                print(f"- Sentence: \"{minor['sentence']}\"")
                print(f"  Field: '{minor['field']}' -> Expected: \"{minor['expected_value']}\", Got: \"{minor['predicted_value']}\"")


if __name__ == "__main__":
    unittest.main()

# Script to run this file: python -m tests.test_fact_extractor
