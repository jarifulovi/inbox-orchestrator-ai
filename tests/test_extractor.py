import json
import re
import unicodedata
from uuid import uuid4
import unittest

from app.models.action_extractor.extractor import ActionExtractor


class ExtractorIntegrationTests(unittest.TestCase):
    def setUp(self):
        with open("tests/files/extractor_test_data_edge.json", "r", encoding="utf-8") as fh:
            self.raw = json.load(fh)

    def test_extractor_against_gold_file(self):
        emails = []
        email_ids = []
        for entry in self.raw:
            # 1. FIX: Format exactly as a dictionary to provide .get() interfaces
            content = entry.get("body") or entry.get("cleaned_body") or entry.get("content", "")
            eid = str(uuid4())

            mock_node = {
                "id": eid,
                "cleaned_body": content
            }

            emails.append(mock_node)  # No longer a tuple! Passes an object with .get()
            email_ids.append(eid)

        try:
            extractor = ActionExtractor()
        except Exception as exc:
            raise unittest.SkipTest(
                "ActionExtractor could not be instantiated (is 'en_core_web_sm' installed?). "
                "Install with: python -m spacy download en_core_web_sm"
            ) from exc

        # Raw prediction execution from the model layer
        results = extractor.predict(emails, batch_size=4)

        # Build a mapping from email_id -> batch response so we don't rely on order
        result_map = {r.get("email_id"): r for r in results if r and "email_id" in r}
        failures = []

        for idx, entry in enumerate(self.raw):
            content = entry.get("body") or entry.get("content") or entry.get("cleaned_body", "")
            expected = entry.get("expected", [])

            # Normalize Expected Pairs to match processor formatting rules
            expected_pairs = set()
            for e in expected:
                raw_v = e.get("verb") or e.get("verb_primitive", "")
                raw_o = e.get("object") or e.get("object_primitive", "")

                v_norm = unicodedata.normalize("NFKC", str(raw_v)).strip().casefold()
                o_norm = unicodedata.normalize("NFKC", str(raw_o)).strip().casefold()
                o_norm = \
                re.split(r"\s+(?:before|after|until|so\s+that|in\s+order\s+to)\b", o_norm, flags=re.IGNORECASE)[
                    0].strip()

                expected_pairs.add((v_norm, o_norm))

            # Lookup predicted pairs by email id (robust against reordering)
            eid = email_ids[idx]
            batch = result_map.get(eid)

            if batch is None:
                predicted_pairs = set()
            else:
                # predict() already runs ActionPostprocessor internally and serializes
                # to dicts via model_dump() — read the actions directly as dicts
                raw_actions = batch.get("actions", [])

                predicted_pairs = set()
                for a in raw_actions:
                    if isinstance(a, dict):
                        v = a.get("verb_primitive", "")
                        o = a.get("object_primitive", "")
                    else:
                        v = getattr(a, "verb_primitive", "")
                        o = getattr(a, "object_primitive", "")

                    predicted_pairs.add((
                        (v or "").strip().casefold(),
                        (o or "").strip().casefold()
                    ))

            # 3. Exact Equality Checks against processed output
            missing_tasks = expected_pairs - predicted_pairs  # Tasks you failed to extract
            unexpected_tasks = predicted_pairs - expected_pairs  # Noise caught by the pipeline gateway
            length_mismatch = len(expected_pairs) != len(predicted_pairs)

            if missing_tasks or unexpected_tasks or length_mismatch:
                failure = {
                    "content": content,
                    "metrics_error": {
                        "expected_count": len(expected_pairs),
                        "predicted_count": len(predicted_pairs),
                        "count_mismatch": length_mismatch
                    },
                    "expected_all_tasks": sorted(list(expected_pairs)),
                    "predicted_all_tasks": sorted(list(predicted_pairs)),
                    "missing_tasks_error": sorted(list(missing_tasks)),
                    "unexpected_noise_error": sorted(list(unexpected_tasks))
                }
                failures.append(failure)

        # 4. Reporting Output Setup
        if failures:
            out_path = "tests/files/extractor_test_failures.json"
            try:
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(failures, fh, indent=2, ensure_ascii=False)
            except Exception:
                print("Failed to write failure file; printing failures below")
                print(json.dumps(failures, indent=2, ensure_ascii=False))

            print(
                f"\nTotal exact-match failures found: {len(failures)}/{len(emails)}. Full logs saved to: {out_path}\n")
            for f in failures:
                print("=" * 60)
                print("FULL SENTENCE:", f["content"])
                print("EXPECTED TASK(S):", f["expected_all_tasks"])
                print("PREDICTED GOT   :", f["predicted_all_tasks"])
                if f["missing_tasks_error"]:
                    print("⛔ MISSING      :", f["missing_tasks_error"])
                if f["unexpected_noise_error"]:
                    print("⚠️ UNEXPECTED   :", f["unexpected_noise_error"])
                print("=" * 60)

            self.fail(
                f"Extractor pipeline failed strict evaluation validation for {len(failures)} sample(s). Check {out_path}")

if __name__ == "__main__":
    unittest.main()