import unittest
import json
import os
import shutil
from pathlib import Path
from scrapers import extract_questions_from_html

class TestAIAdapters(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path("data/adapters")
        self.active_path = self.data_dir / "active_adapters.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.active_path.exists():
            self.backup = self.active_path.read_text()
        else:
            self.backup = None

    def tearDown(self):
        if self.backup:
            self.active_path.write_text(self.backup)
        elif self.active_path.exists():
            self.active_path.unlink()

    def test_dynamic_adapter_loading(self):
        # Create a mock adapter
        adapter_code = """
class MockParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.questions = []
    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.in_h1 = True
    def handle_data(self, data):
        if hasattr(self, 'in_h1') and self.in_h1:
            self.questions.append(data)
            self.in_h1 = False
"""
        adapter = {
            "id": "test-id",
            "domain": "test.com",
            "parser_code": adapter_code
        }
        self.active_path.write_text(json.dumps([adapter]))

        html = "<h1>How are you?</h1>"
        res = extract_questions_from_html(html, "http://test.com/apply")

        self.assertIn("How are you?", res["questions"])
        self.assertEqual(res["source"], "ai-adapter-test-id")

if __name__ == "__main__":
    unittest.main()
