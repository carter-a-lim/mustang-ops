import json
import unittest
from pathlib import Path
import tempfile
import os
import shutil
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Import the worker functions
import jobs.autofill_worker as worker

class TestAutofillRobust(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.data_dir = self.root_dir / "data"
        self.data_dir.mkdir()
        self.artifacts_dir = self.data_dir / "artifacts"
        self.artifacts_dir.mkdir()

        self.queue_path = self.data_dir / "assisted_apply_queue.json"

        # Patch paths in worker
        worker.DATA_DIR = self.data_dir
        worker.ASSISTED_QUEUE_PATH = self.queue_path
        worker.ARTIFACTS_DIR = self.artifacts_dir

        self.test_job_id = "test-job-robust"
        self.initial_data = {
            "queue": [
                {
                    "id": self.test_job_id,
                    "company": "Test Robust Corp",
                    "apply_url": "http://example.com",
                    "status": "needs-review"
                }
            ]
        }
        self.queue_path.write_text(json.dumps(self.initial_data))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_update_job_status_with_attempts(self):
        attempt_info = {
            "attempt": 1,
            "mode": "dry-run",
            "status": "success",
            "artifacts": {"screenshot": "path/to/ss.png"}
        }
        worker.update_job_status(self.test_job_id, "needs-approval", attempt_info=attempt_info)

        data = json.loads(self.queue_path.read_text())
        job = data["queue"][0]
        self.assertEqual(job["status"], "needs-approval")
        self.assertEqual(len(job["attempts"]), 1)
        self.assertEqual(job["attempts"][0]["status"], "success")
        self.assertEqual(job["attempts"][0]["artifacts"]["screenshot"], "path/to/ss.png")

    @patch("jobs.autofill_worker.fill_form")
    @patch("jobs.autofill_worker.sync_playwright")
    @patch("jobs.autofill_worker.get_job")
    def test_live_submit_unapproved_fails(self, mock_get_job, mock_playwright, mock_fill):
        # Mock job as still needing review
        mock_get_job.return_value = {
            "id": self.test_job_id,
            "status": "needs-review",
            "apply_url": "http://example.com"
        }

        # Mock playwright to avoid actual browser launch
        mock_p = mock_playwright.return_value.__enter__.return_value
        mock_browser = mock_p.chromium.launch.return_value
        mock_page = mock_browser.new_context.return_value.new_page.return_value
        mock_page.content.return_value = "<html></html>"

        with patch("sys.argv", ["autofill_worker.py", self.test_job_id, "live"]):
            worker.main()

        data = json.loads(self.queue_path.read_text())
        job = data["queue"][0]
        self.assertEqual(job["status"], "error")
        self.assertIn("UNAPPROVED_SUBMIT_ATTEMPT", job["last_error"])
        self.assertEqual(job["attempts"][0]["error_code"], "UNAPPROVED_SUBMIT_ATTEMPT")

    @patch("jobs.autofill_worker.sync_playwright")
    @patch("time.sleep", return_value=None) # Skip backoff delay
    def test_retry_on_navigation_failure(self, mock_sleep, mock_playwright):
        # Mock playwright to fail navigation
        mock_p = mock_playwright.return_value.__enter__.return_value
        mock_browser = mock_p.chromium.launch.return_value
        mock_page = mock_browser.new_context.return_value.new_page.return_value
        mock_page.goto.side_effect = Exception("Network error")

        with patch("sys.argv", ["autofill_worker.py", self.test_job_id, "dry-run"]):
            worker.main()

        data = json.loads(self.queue_path.read_text())
        job = data["queue"][0]
        self.assertEqual(len(job["attempts"]), 3) # Should have tried 3 times
        for attempt in job["attempts"]:
            self.assertEqual(attempt["error_code"], "NAVIGATION_FAILED")

if __name__ == "__main__":
    unittest.main()
