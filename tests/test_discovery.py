import unittest
import json
import os
from pathlib import Path
from jobs.discovery_agent import main as discovery_main

class TestDiscoveryAgent(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.discovered_path = self.root / "data" / "discovered_sources.json"
        # Mock LLM to avoid real API calls
        import llm
        self.original_call = llm.call_openclaw
        llm.call_openclaw = self.mock_call_openclaw

    def tearDown(self):
        import llm
        llm.call_openclaw = self.original_call
        if self.discovered_path.exists():
            os.remove(self.discovered_path)

    def mock_call_openclaw(self, messages, model=None):
        return json.dumps([
            {
                "name": "Test Board",
                "url": "https://test.com",
                "description": "A test board",
                "quality_score": 85,
                "update_frequency": "daily",
                "signal_level": "high",
                "value_prop": "High signal"
            }
        ])

    def test_discovery_run(self):
        discovery_main()
        self.assertTrue(self.discovered_path.exists())
        data = json.loads(self.discovered_path.read_text())
        self.assertEqual(len(data["sources"]), 1)
        self.assertEqual(data["sources"][0]["name"], "Test Board")
        self.assertEqual(data["sources"][0]["final_score"], 95) # 85 + 10 (high signal bonus)

if __name__ == "__main__":
    unittest.main()
