import unittest

from app.core.models.action_extractor.components.processors import ActionPostprocessor, TextPreprocessor


class DummyAction:
    def __init__(self, verb_primitive, object_primitive, source_sentence):
        self.verb_primitive = verb_primitive
        self.object_primitive = object_primitive
        self.source_sentence = source_sentence


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


class ActionPostprocessorTests(unittest.TestCase):
    def test_clean_filters_casual_verbs(self):
        actions = [
            DummyAction("leave", "office", "Please leave the office."),
            DummyAction("review", "draft", "Please review the draft."),
        ]

        cleaned = ActionPostprocessor.clean(actions)  # type: ignore[arg-type]
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0].verb_primitive, "review")

    def test_process_filters_then_deduplicates(self):
        actions = [
            DummyAction("watch", "video", "Please watch the tutorial."),
            DummyAction("review", "draft", "Please review the draft."),
            DummyAction("review", "draft", "Please review the draft."),
        ]

        processed = ActionPostprocessor.process(actions)  # type: ignore[arg-type]
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0]["verb_primitive"], "review")


if __name__ == "__main__":
    unittest.main()




