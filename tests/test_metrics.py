import unittest
from unittest.mock import patch

import app


class MetricsTests(unittest.TestCase):
    @patch("app.get_network_jobs")
    @patch("app.get_assisted_apply_queue")
    @patch("app._read_json_file")
    def test_metrics(self, mock_read_json, mock_queue, mock_jobs):
        def _read_side_effect(path, default):
            if str(path).endswith("simplify_software_internships.json"):
                return {"roles": [{}, {}, {}, {}, {}]} # 5 roles
            if str(path).endswith("auto_apply_state.json"):
                return {"applications": []}
            return default

        mock_read_json.side_effect = _read_side_effect
        mock_jobs.return_value = {
            "roles": [
                {"source": "simplify"}, {"source": "simplify"}, {"source": "simplify"}, {"source": "simplify"}, {"source": "simplify"}, # from snapshot
                {"source": "manual"}, {"source": "manual"} # 2 manual
            ],
            "applications": [
                {"stage": "Applied"},
                {"stage": "OA"},
                {"stage": "Interview"},
                {"stage": "Rejected"},
                {"stage": "Offer"},
            ],
        }
        mock_queue.return_value = {
            "queue": [
                {"status": "needs-review"},
                {"status": "approved"},
                {"status": "submitted"},
            ]
        }

        metrics = app.get_network_metrics()
        self.assertEqual(metrics["pipeline"]["ingest_total"], 7) # 5 simplify + 2 manual
        self.assertEqual(metrics["pipeline"]["qualified"]["currently_queued"], 2)
        self.assertGreaterEqual(metrics["pipeline"]["qualified"]["total"], 7)

        self.assertEqual(metrics["pipeline"]["applications"]["total_submitted"], 5)
        self.assertEqual(metrics["pipeline"]["outcomes"]["oa"], 1)
        self.assertEqual(metrics["pipeline"]["outcomes"]["interview"], 1)
        self.assertEqual(metrics["pipeline"]["outcomes"]["rejected"], 1)
        self.assertEqual(metrics["pipeline"]["outcomes"]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
