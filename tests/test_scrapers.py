import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
from scrapers import extract_questions_from_html

client = TestClient(app.app)


class TestScrapers(unittest.TestCase):
    def test_greenhouse_parser(self):
        html = """
        <div class="field">
            <label>First Name<br><span class="req">*</span></label>
            <input type="text">
        </div>
        <div class="field">
            <label>Why do you want to work here? *</label>
            <textarea></textarea>
        </div>
        """
        questions = extract_questions_from_html(html, "boards.greenhouse.io")
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0], "Why do you want to work here?")

    def test_lever_parser(self):
        html = """
        <label class="application-label">First name</label>
        <div class="application-question">What is your favorite color? *</div>
        <textarea></textarea>
        """
        questions = extract_questions_from_html(html, "jobs.lever.co")
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0], "What is your favorite color?")

    @patch("app._generate_draft_answers")
    def test_generate_endpoint(self, mock_generate):
        mock_generate.return_value = {"Why here?": "Because it's cool."}

        response = client.post(
            "/api/network/apply/generate",
            json={
                "company": "TestCo",
                "title": "SWE",
                "questions": ["Why here?"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answers"]["Why here?"], "Because it's cool.")

    @patch("scrapers.extract_questions_from_html")
    def test_scrape_endpoint(self, mock_extract):
        mock_extract.return_value = ["Q1", "Q2"]

        response = client.post(
            "/api/network/apply/scrape",
            json={
                "html": "<html></html>",
                "company": "TestCo",
                "title": "SWE",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["questions"], ["Q1", "Q2"])


if __name__ == "__main__":
    unittest.main()
