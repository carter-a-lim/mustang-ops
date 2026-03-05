import unittest
from unittest.mock import patch
import json
import app

class AnswerQualityTests(unittest.TestCase):
    def setUp(self):
        self.style_profile = {
            "content_rules": {
                "avoid": ["innovative", "synergy"],
                "prioritize": ["speed", "ownership"]
            }
        }

    def test_check_answer_quality_too_short(self):
        answer = "I am good."
        reasons = app._check_answer_quality(answer, "Tell us about yourself", self.style_profile)
        self.assertIn("Answer is too short (less than 50 characters)", reasons)

    def test_check_answer_quality_buzzwords(self):
        answer = "I am innovative and I love synergy in teams. I have been working on many projects for a long time."
        reasons = app._check_answer_quality(answer, "Tell us about yourself", self.style_profile)
        self.assertTrue(any("innovative" in r for r in reasons))
        self.assertTrue(any("synergy" in r for r in reasons))

    def test_check_answer_quality_generic_filler(self):
        answer = "I am a passionate and hard-working student who wants to learn new things every day at your company."
        reasons = app._check_answer_quality(answer, "Tell us about yourself", self.style_profile)
        self.assertTrue(any("passionate" in r for r in reasons))
        self.assertTrue(any("hard-working" in r for r in reasons))

    def test_check_answer_quality_lack_specificity(self):
        answer = "I have worked on many projects and I am very good at what I do. I am a great team player as well."
        reasons = app._check_answer_quality(answer, "Tell us about yourself", self.style_profile)
        self.assertIn("Answer lacks specificity (no numbers, tech terms, or prioritized keywords)", reasons)

    def test_check_answer_quality_good_answer(self):
        answer = "I built a Python scraper that processed 50,000 records per hour, improving speed and ownership of our data pipeline."
        reasons = app._check_answer_quality(answer, "Tell us about yourself", self.style_profile)
        self.assertEqual(len(reasons), 0)

    @patch("app._call_openclaw")
    @patch("app._load_resume_profile")
    @patch("app._load_answer_memory")
    @patch("app._load_style_profile")
    def test_generate_draft_answers_revision_loop(self, mock_style, mock_memory, mock_resume, mock_call):
        mock_style.return_value = self.style_profile
        mock_resume.return_value = {"profile": {"skills": ["python"]}}
        mock_memory.return_value = {"entries": []}

        # First call returns a bad answer, second returns a good one
        mock_call.side_effect = [
            "I am a passionate student.", # Bad: too short, generic
            "I built a Python scraper that processed 50,000 records per hour." # Good
        ]

        answers = app._generate_draft_answers("Company X", "Intern", ["Tell us about yourself"])

        self.assertIn("Tell us about yourself", answers)
        self.assertEqual(answers["Tell us about yourself"]["answer"], "I built a Python scraper that processed 50,000 records per hour.")
        self.assertIn("revision_reason", answers["Tell us about yourself"])
        self.assertEqual(mock_call.call_count, 2)

if __name__ == "__main__":
    unittest.main()
