import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app

client = TestClient(app.app)


class CalendarEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.context_path = Path(self.tmp.name) / "context.json"
        self.context_path.write_text(json.dumps({"updated_at": None, "events": [], "deadlines": []}))

        self.old_context_path = app.CONTEXT_PATH
        app.CONTEXT_PATH = self.context_path

    def tearDown(self):
        app.CONTEXT_PATH = self.old_context_path
        self.tmp.cleanup()

    @patch("app.subprocess.run")
    @patch("app.os.getenv")
    def test_create_calendar_event_success(self, mock_getenv, mock_run):
        mock_getenv.side_effect = lambda k, default=None: {
            "GOG_ACCOUNT": "carter.limster@gmail.com",
            "GOG_CALENDAR_ID": "primary",
        }.get(k, default)
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps({"event": {"id": "evt-123"}})

        res = client.post(
            "/api/calendar/events",
            json={
                "title": "Interview",
                "start": "2026-03-06T15:00",
                "end": "2026-03-06T15:30",
                "location": "Zoom",
                "description": "test",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["id"], "evt-123")

        ctx = json.loads(self.context_path.read_text())
        self.assertEqual(len(ctx["events"]), 1)
        self.assertEqual(ctx["events"][0]["id"], "evt-123")

    @patch("app.subprocess.run")
    @patch("app.os.getenv")
    def test_delete_calendar_event_success(self, mock_getenv, mock_run):
        self.context_path.write_text(
            json.dumps({"updated_at": None, "events": [{"id": "evt-123", "title": "X", "date": "2026-03-06"}]})
        )
        mock_getenv.side_effect = lambda k, default=None: {
            "GOG_ACCOUNT": "carter.limster@gmail.com",
            "GOG_CALENDAR_ID": "primary",
        }.get(k, default)
        mock_run.return_value.returncode = 0

        res = client.delete("/api/calendar/events/evt-123")
        self.assertEqual(res.status_code, 200)

        ctx = json.loads(self.context_path.read_text())
        self.assertEqual(len(ctx["events"]), 0)

    @patch("app.os.getenv")
    def test_missing_account(self, mock_getenv):
        mock_getenv.side_effect = lambda k, default=None: None if k == "GOG_ACCOUNT" else default
        res = client.post("/api/calendar/events", json={"title": "x", "start": "2026-03-06"})
        self.assertEqual(res.status_code, 500)


if __name__ == "__main__":
    unittest.main()
