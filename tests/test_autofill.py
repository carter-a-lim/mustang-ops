import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app

client = TestClient(app.app)


class TestAutofillFeature(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.queue_path = Path(self.temp_dir.name) / "assisted_apply_queue.json"

        self.old_queue_path = app.ASSISTED_QUEUE_PATH
        app.ASSISTED_QUEUE_PATH = self.queue_path

        self.test_job_id = "test-job-123"
        payload = {
            "queue": [
                {
                    "id": self.test_job_id,
                    "company": "TestCorp",
                    "apply_url": "https://example.com/apply",
                    "status": "needs-review",
                }
            ]
        }
        self.queue_path.write_text(json.dumps(payload))

    def tearDown(self):
        app.ASSISTED_QUEUE_PATH = self.old_queue_path
        self.temp_dir.cleanup()

    def test_update_queue_item_status(self):
        res = client.patch(f"/api/network/apply/queue/{self.test_job_id}", json={"status": "approved"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "approved")

    @patch("app.subprocess.Popen")
    def test_execute_autofill_dry_run(self, mock_popen):
        res = client.post(f"/api/network/apply/queue/{self.test_job_id}/execute", json={"mode": "dry-run"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["mode"], "dry-run")
        mock_popen.assert_called_once()

    @patch("app.subprocess.Popen")
    def test_execute_autofill_live(self, mock_popen):
        res = client.post(f"/api/network/apply/queue/{self.test_job_id}/execute", json={"mode": "live"})
        self.assertEqual(res.status_code, 200)
        mock_popen.assert_called_once()

    def test_execute_autofill_invalid_job(self):
        res = client.post("/api/network/apply/queue/bad-id/execute", json={"mode": "live"})
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
