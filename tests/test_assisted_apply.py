import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class AssistedApplyTests(unittest.TestCase):
    def test_extract_resume_profile(self):
        text = """
        Class of 2029
        Skills: Python, JavaScript, TypeScript, React, Node.js, Firebase, Supabase
        """
        profile = app._extract_resume_profile(text)
        self.assertEqual(profile["grad_year"], 2029)
        self.assertIn("python", profile["skills"])
        self.assertIn("javascript", profile["skills"])
        self.assertIn("react", profile["skills"])

    def test_prepare_assisted_apply_queue_uses_resume_fit(self):
        roles_payload = {
            "roles": [
                {
                    "company": "Alpha",
                    "title": "Software Engineer Intern",
                    "location": "Remote",
                    "apply_url": "https://example.com/a",
                    "source": "simplify",
                },
                {
                    "company": "Beta",
                    "title": "Mechanical Design Intern",
                    "location": "CA",
                    "apply_url": "https://example.com/b",
                    "source": "simplify",
                },
            ]
        }
        resume_payload = {
            "profile": {
                "skills": ["python", "javascript", "react", "node"],
                "grad_year": 2029,
                "work_auth": "unknown",
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            old_queue_path = app.ASSISTED_QUEUE_PATH
            app.ASSISTED_QUEUE_PATH = queue_path
            try:
                with patch("app.get_network_jobs", return_value=roles_payload), patch(
                    "app._load_resume_profile", return_value=resume_payload
                ):
                    result = app.prepare_assisted_apply_queue(
                        app.AssistedQueueBuildBody(limit=10, use_resume_fit=True)
                    )

                self.assertEqual(result["count"], 1)
                self.assertEqual(result["queue"][0]["company"], "Alpha")
                self.assertIn("fit_score", result["queue"][0])
                self.assertTrue(queue_path.exists())
                saved = json.loads(queue_path.read_text())
                self.assertEqual(saved["count"], 1)
            finally:
                app.ASSISTED_QUEUE_PATH = old_queue_path


if __name__ == "__main__":
    unittest.main()
