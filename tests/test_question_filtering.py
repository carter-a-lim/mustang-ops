import unittest
from unittest.mock import patch

import app


class QuestionFilteringTests(unittest.TestCase):
    def test_heuristic_removes_noise(self):
        questions = [
            "Attach",
            "Enter manually",
            "What is your GPA?",
            "Why do you want this role?",
            "Email",
        ]
        filtered, meta = app._filter_questions_for_answering(questions)
        self.assertIn("What is your GPA?", filtered)
        self.assertIn("Why do you want this role?", filtered)
        self.assertNotIn("Attach", filtered)
        self.assertNotIn("Enter manually", filtered)
        self.assertGreaterEqual(meta.get("removed", 0), 2)

    @patch("app._classify_questions_with_groq")
    def test_groq_labels_remove_ui_noise(self, mock_classify):
        mock_classify.return_value = {
            "When do you graduate?": "basic_profile_field",
            "Close sidebar": "ui_noise",
        }
        filtered, meta = app._filter_questions_for_answering([
            "When do you graduate?",
            "Close sidebar",
        ])
        self.assertEqual(filtered, ["When do you graduate?"])
        self.assertEqual(meta.get("method"), "heuristic+groq")


if __name__ == "__main__":
    unittest.main()
