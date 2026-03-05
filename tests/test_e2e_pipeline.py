import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app
from jobs import auto_apply_orchestrator as orch
from jobs import scrape_simplify_jobs as scrape
from jobs import sync_gmail

client = TestClient(app.app)

class TestE2EPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.tmp_dir.name)

        # Override data paths in all relevant modules
        self.patchers = []

        modules_to_patch = [app, orch, scrape, sync_gmail]
        for mod in modules_to_patch:
            # Common paths
            if hasattr(mod, "DATA_DIR"):
                p = patch.object(mod, "DATA_DIR", self.data_path)
                p.start()
                self.patchers.append(p)
            if hasattr(mod, "JOB_PIPELINE_PATH"):
                p = patch.object(mod, "JOB_PIPELINE_PATH", self.data_path / "job_pipeline.json")
                p.start()
                self.patchers.append(p)
            if hasattr(mod, "ASSISTED_QUEUE_PATH"):
                p = patch.object(mod, "ASSISTED_QUEUE_PATH", self.data_path / "assisted_apply_queue.json")
                p.start()
                self.patchers.append(p)
            if hasattr(mod, "AUTO_STATE_PATH"):
                p = patch.object(mod, "AUTO_STATE_PATH", self.data_path / "auto_apply_state.json")
                p.start()
                self.patchers.append(p)
            if hasattr(mod, "RESUME_PROFILE_PATH"):
                p = patch.object(mod, "RESUME_PROFILE_PATH", self.data_path / "resume_profile.json")
                p.start()
                self.patchers.append(p)

        # Module specific overrides in scrape
        p = patch.object(scrape, "JSON_PATH", self.data_path / "simplify_software_internships.json")
        p.start()
        self.patchers.append(p)
        p = patch.object(scrape, "CSV_PATH", self.data_path / "simplify_software_internships.csv")
        p.start()
        self.patchers.append(p)

        # Mock resume profile for fit scoring
        resume_profile = {
            "updated_at": "2024-01-01T00:00:00Z",
            "profile": {
                "skills": ["python", "javascript", "react"],
                "grad_year": 2026,
                "work_auth": "us-citizen"
            }
        }
        (self.data_path / "resume_profile.json").write_text(json.dumps(resume_profile))

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp_dir.cleanup()

    @patch("requests.get")
    @patch("subprocess.run")
    def test_happy_path_e2e(self, mock_run, mock_get):
        # 1. Ingest: Scrape SimplifyJobs
        mock_md = """
## 💻 Software Engineering Internship Roles
<table>
<tbody>
<tr>
<td>Google</td>
<td>[SWE Intern](https://google.com/apply)</td>
<td>Mountain View, CA</td>
<td><a href="https://google.com/apply">Apply</a></td>
<td><img src="https://img.shields.io/badge/Nov%2015-blue" /></td>
</tr>
<tr>
<td>LowFitCorp</td>
<td>[Mechanical Intern](https://lowfit.com/apply)</td>
<td>Remote</td>
<td><a href="https://lowfit.com/apply">Apply</a></td>
<td><img src="https://img.shields.io/badge/Nov%2014-blue" /></td>
</tr>
</tbody>
</table>
"""
        mock_get.return_value.text = mock_md
        mock_get.return_value.status_code = 200

        scrape.main()
        self.assertTrue((self.data_path / "simplify_software_internships.json").exists())

        # 2. Qualify: Prepare Assisted Apply Queue
        res = client.post("/api/network/apply/prepare", json={
            "limit": 10,
            "use_resume_fit": True
        })
        self.assertEqual(res.status_code, 200)
        queue_data = res.json()
        self.assertEqual(len(queue_data["queue"]), 1)
        self.assertEqual(queue_data["queue"][0]["company"], "Google")

        # 3. Queue: Orchestrator stages
        # Direct call to avoid subprocess output parsing issues in TestClient/Popen environment
        result = orch.run(stage="all", max_submit=10, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["prepared"], 1)
        self.assertEqual(result["stats"]["queued_for_approval"], 1)

        # Verify state
        state = json.loads((self.data_path / "auto_apply_state.json").read_text())
        self.assertEqual(state["applications"][0]["status"], "approval-queued")

        # 4. Approve: Manual approval
        state["applications"][0]["approval"]["decision"] = "approved"
        (self.data_path / "auto_apply_state.json").write_text(json.dumps(state))

        # 5. Submit: Orchestrator submit
        result = orch.run(stage="submit", max_submit=10, dry_run=False)
        self.assertEqual(result["stats"]["submitted"], 1)

        # Verify submitted status
        state = json.loads((self.data_path / "auto_apply_state.json").read_text())
        self.assertEqual(state["applications"][0]["status"], "submitted")

        # 6. Gmail outcome: Sync Gmail
        # Mock gog gmail search result
        mock_emails = [
            {
                "subject": "Interview Invitation: Google",
                "snippet": "We would like to invite you for an interview for the SWE Intern position.",
                "from": "recruiter@google.com",
                "date": "2024-11-20"
            }
        ]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_emails))

        with patch.dict(os.environ, {"GOG_ACCOUNT": "test@example.com"}):
            sync_gmail.main()

        # Verify status update in auto_state
        state = json.loads((self.data_path / "auto_apply_state.json").read_text())
        self.assertEqual(state["applications"][0]["status"], "interview")

        # 7. Metrics validation
        res = client.get("/api/network/metrics")
        self.assertEqual(res.status_code, 200)
        metrics = res.json()
        self.assertEqual(metrics["pipeline"]["ingest_total"], 2)
        self.assertEqual(metrics["pipeline"]["outcomes"]["interview"], 1)
        self.assertEqual(metrics["pipeline"]["applications"]["total_submitted"], 1)

    def test_failure_low_fit_ignored(self):
        # Setup Simplify data with a low-fit role
        mock_md = """
## 💻 Software Engineering Internship Roles
<table>
<tbody>
<tr>
<td>BadFit</td>
<td>[Marketing Intern](https://badfit.com/apply)</td>
<td>Remote</td>
<td><a href="https://badfit.com/apply">Apply</a></td>
<td><img src="https://img.shields.io/badge/Nov%2014-blue" /></td>
</tr>
</tbody>
</table>
"""
        with patch("requests.get") as mock_get:
            mock_get.return_value.text = mock_md
            mock_get.return_value.status_code = 200
            scrape.main()

        res = client.post("/api/network/apply/prepare", json={"use_resume_fit": True})
        self.assertEqual(res.json()["count"], 0)

    def test_failure_unauthorized_submit(self):
        # Prepare an application in the state file
        (self.data_path / "auto_apply_state.json").write_text(json.dumps({
            "applications": [{
                "key": "Acme::Intern::http://x.com",
                "company": "Acme", "title": "Intern", "apply_url": "http://x.com",
                "status": "approval-queued",
                "approval": {"decision": "pending"}
            }]
        }))

        # Try to submit
        result = orch.run(stage="submit", max_submit=10, dry_run=False)
        self.assertEqual(result["stats"]["submitted"], 0)

        state = json.loads((self.data_path / "auto_apply_state.json").read_text())
        self.assertEqual(state["applications"][0]["status"], "approval-queued")

    def test_failure_empty_ingest(self):
        # Empty markdown with enough to satisfy _extract_section but fail _parse_rows or at least produce 0
        mock_md = "## 💻 Software Engineering Internship Roles\n<table><tbody></tbody></table>"
        with patch("requests.get") as mock_get:
            mock_get.return_value.text = mock_md
            mock_get.return_value.status_code = 200
            scrape.main()

        res = client.post("/api/network/apply/prepare", json={"use_resume_fit": True})
        data = res.json()
        self.assertEqual(data.get("count", len(data.get("queue", []))), 0)

        res = client.get("/api/network/metrics")
        self.assertEqual(res.json()["pipeline"]["ingest_total"], 0)

if __name__ == "__main__":
    unittest.main()
