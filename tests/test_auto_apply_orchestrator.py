import json
import tempfile
import unittest
from pathlib import Path

from jobs import auto_apply_orchestrator as orch


class AutoApplyOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

        self.old_queue_path = orch.ASSISTED_QUEUE_PATH
        self.old_state_path = orch.AUTO_STATE_PATH

        orch.ASSISTED_QUEUE_PATH = self.tmp_path / "assisted_apply_queue.json"
        orch.AUTO_STATE_PATH = self.tmp_path / "auto_apply_state.json"

    def tearDown(self):
        orch.ASSISTED_QUEUE_PATH = self.old_queue_path
        orch.AUTO_STATE_PATH = self.old_state_path
        self.tmp.cleanup()

    def _write_queue(self):
        payload = {
            "queue": [
                {
                    "company": "Acme",
                    "title": "Software Engineer Intern",
                    "location": "Remote",
                    "apply_url": "https://jobs.example.com/acme",
                    "source": "simplify",
                    "fit_score": 88,
                    "fit_tier": "strong-fit",
                },
                {
                    "company": "Beta",
                    "title": "Backend Intern",
                    "location": "SF",
                    "apply_url": "https://jobs.example.com/beta",
                    "source": "network",
                    "fit_score": 73,
                    "fit_tier": "reach",
                },
            ]
        }
        orch.save_json(orch.ASSISTED_QUEUE_PATH, payload)

    def _load_state(self):
        return json.loads(orch.AUTO_STATE_PATH.read_text())

    def test_stage_all_builds_approval_queue(self):
        self._write_queue()

        result = orch.run(stage="all", max_submit=10, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["prepared"], 2)
        self.assertEqual(result["stats"]["enriched"], 2)
        self.assertEqual(result["stats"]["drafted"], 2)
        self.assertEqual(result["stats"]["queued_for_approval"], 2)
        self.assertEqual(result["stats"]["submitted"], 0)

        state = self._load_state()
        self.assertEqual(len(state["applications"]), 2)
        self.assertTrue(all(a["status"] == "approval-queued" for a in state["applications"]))
        self.assertTrue(all(a.get("draft") for a in state["applications"]))

    def test_submit_only_approved(self):
        self._write_queue()
        orch.run(stage="all", max_submit=10, dry_run=False)

        state = self._load_state()
        apps = state["applications"]
        apps[0]["approval"]["decision"] = "approved"
        apps[1]["approval"]["decision"] = "pending"
        orch.save_json(orch.AUTO_STATE_PATH, state)

        submit_result = orch.run(stage="submit", max_submit=10, dry_run=False)
        self.assertEqual(submit_result["stats"]["submitted"], 1)

        updated = self._load_state()
        statuses = {a["company"]: a["status"] for a in updated["applications"]}
        self.assertEqual(statuses["Acme"], "submitted")
        self.assertEqual(statuses["Beta"], "approval-queued")

    def test_submit_dry_run_does_not_change_status(self):
        self._write_queue()
        orch.run(stage="all", max_submit=10, dry_run=False)

        state = self._load_state()
        for app in state["applications"]:
            app["approval"]["decision"] = "approved"
        orch.save_json(orch.AUTO_STATE_PATH, state)

        submit_result = orch.run(stage="submit", max_submit=10, dry_run=True)
        self.assertEqual(submit_result["stats"]["submitted"], 0)

        updated = self._load_state()
        self.assertTrue(all(a["status"] == "approval-queued" for a in updated["applications"]))


if __name__ == "__main__":
    unittest.main()
