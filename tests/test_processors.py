import unittest

from app.core.ml_models.fact_extractor.components.processors import FactPostprocessor, TextPreprocessor


class TextPreprocessorTests(unittest.TestCase):
    def test_clean_pipeline_expands_contractions_and_normalizes_phrases(self):
        text = "<p>Kindly ensure that you don't send the report by EOD.</p>"
        self.assertEqual(
            TextPreprocessor.clean(text),
            "please do not send the report by end of day.",
        )

    def test_clean_pipeline_removes_html_and_reply_noise(self):
        text = "On Tue, Alice wrote:\n> Please can you review the draft when you get a chance?"
        cleaned = TextPreprocessor.clean(text)
        self.assertNotIn(">", cleaned)
        self.assertNotIn("wrote", cleaned.lower())
        self.assertIn("review the draft", cleaned.lower())
        self.assertTrue(cleaned.lower().startswith("please"))


class FactPostprocessorTests(unittest.TestCase):
    def test_clean_filters_casual_verbs(self):
        facts = [
            {
                "fact_type": "task",
                "payload": {"action": "leave", "object": "office"},
                "source_sentence": "Please leave the office."
            },
            {
                "fact_type": "task",
                "payload": {"action": "review", "object": "draft"},
                "source_sentence": "Please review the draft."
            },
        ]

        cleaned = FactPostprocessor.process(facts)
        # 'leave' is a casual verb and should be demoted to a regular 'fact' type rather than dropped completely,
        # unless it is in HARD_DELETE_VERBS (which leave is not, it is in CASUAL_VERBS).
        # Wait, let's verify what CASUAL_VERBS does in processors.py:
        # If it is a casual verb, fact_type is demoted to "fact".
        self.assertEqual(len(cleaned), 2)
        # The first one should have fact_type = "fact"
        self.assertEqual(cleaned[0]["fact_type"], "fact")
        # The second one should have fact_type = "task"
        self.assertEqual(cleaned[1]["fact_type"], "task")
        self.assertEqual(cleaned[1]["payload"]["action"], "review")

    def test_process_filters_then_deduplicates(self):
        facts = [
            {
                "fact_type": "task",
                "payload": {"action": "watch", "object": "video"},
                "source_sentence": "Please watch the tutorial."
            },
            {
                "fact_type": "task",
                "payload": {"action": "review", "object": "draft"},
                "source_sentence": "Please review the draft."
            },
            {
                "fact_type": "task",
                "payload": {"action": "review", "object": "draft"},
                "source_sentence": "Please review the draft."
            },
        ]

        processed = FactPostprocessor.process(facts)
        # 'watch' is a casual verb -> demoted to fact
        # The two 'review' actions are duplicates, so one is deduplicated.
        # So we should have 2 unique facts: 1 'fact' (watch) and 1 'task' (review).
        self.assertEqual(len(processed), 2)
        
        types = [f["fact_type"] for f in processed]
        self.assertIn("fact", types)
        self.assertIn("task", types)


if __name__ == "__main__":
    unittest.main()
