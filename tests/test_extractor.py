import json
from uuid import uuid4
import unittest

from app.models.action_extractor.extractor import ActionExtractor


class ExtractorIntegrationTests(unittest.TestCase):
    def setUp(self):
        with open("tests/files/extractor_test_data.json", "r", encoding="utf-8") as fh:
            self.raw = json.load(fh)

    def test_extractor_against_gold_file(self):
        emails = []
        email_ids = []
        for entry in self.raw:
            content = entry["content"]
            eid = uuid4()
            emails.append((eid, content))
            email_ids.append(eid)

        try:
            extractor = ActionExtractor()
        except Exception as exc:
            raise unittest.SkipTest(
                "ActionExtractor could not be instantiated (is 'en_core_web_sm' installed?). "
                "Install with: python -m spacy download en_core_web_sm"
            ) from exc

        results = extractor.process_emails_bulk(emails, batch_size=4)

        # Build a mapping from email_id -> batch response so we don't rely on order
        result_map = {r.email_id: r for r in results}
        failures = []

        for idx, entry in enumerate(self.raw):
            content = entry.get("content")
            expected = entry.get("expected", [])

            # 1. Normalize Expected Pairs
            expected_pairs = set(
                (
                    (e.get("verb", "").strip().casefold(), (e.get("object", "") or "").strip().casefold())
                )
                for e in expected
            )

            # 2. Lookup predicted pairs by email id (robust against reordering)
            eid = email_ids[idx]
            batch = result_map.get(eid)
            if batch is None:
                predicted_pairs = set()
            else:
                predicted_pairs = set(
                    (
                        (a.verb_primitive or "").strip().casefold(),
                        (a.object_primitive or "").strip().casefold(),
                    )
                    for a in batch.actions
                )

            # 3. CRITICAL FIX: Strict Exact Equality Checks
            missing_tasks = expected_pairs - predicted_pairs    # Tasks you failed to extract
            unexpected_tasks = predicted_pairs - expected_pairs # Hidden noise/extra tasks sneaking in
            length_mismatch = len(expected_pairs) != len(predicted_pairs)

            # If any condition hits, capture the entire context sentence with all tasks
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

            print(f"\nTotal exact-match failures found: {len(failures)}/{len(emails)}. Full logs saved to: {out_path}\n")
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

            self.fail(f"Extractor failed strict validation for {len(failures)} sample(s). Check {out_path}")

if __name__ == "__main__":
    unittest.main()