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
        res = extract_questions_from_html(html, "boards.greenhouse.io")
        self.assertEqual(len(res["questions"]), 1)
        self.assertEqual(res["questions"][0], "Why do you want to work here?")
        self.assertEqual(res["source"], "greenhouse")

    def test_lever_parser(self):
        html = """
        <label class="application-label">First name</label>
        <div class="application-question">What is your favorite color? *</div>
        <textarea></textarea>
        """
        res = extract_questions_from_html(html, "jobs.lever.co")
        self.assertEqual(len(res["questions"]), 1)
        self.assertEqual(res["questions"][0], "What is your favorite color?")
        self.assertEqual(res["source"], "lever")

    def test_ashby_pattern(self):
        html = """
        <div>Why do you want to join our startup?</div>
        <label>Email</label>
        <div data-testid="question-field">Tell us about a project you shipped</div>
        """
        res = extract_questions_from_html(html, "https://jobs.ashbyhq.com/company/role/application")
        self.assertIn("Why do you want to join our startup?", res["questions"])
        self.assertIn("Tell us about a project you shipped", res["questions"])

    def test_workday_pattern(self):
        html = """
        <div data-automation-id="questionLabel">Are you legally authorized to work in the US?</div>
        <label>First Name</label>
        """
        res = extract_questions_from_html(html, "https://company.wd1.myworkdayjobs.com/en-US/careers/job/123")
        self.assertIn("Are you legally authorized to work in the US?", res["questions"])

    def test_smartrecruiters_parser(self):
        html = """
        <label>First Name</label>
        <label class="question">What is your desired salary?</label>
        <input name="salary">
        """
        res = extract_questions_from_html(html, "https://jobs.smartrecruiters.com/company/123")
        self.assertIn("What is your desired salary?", res["questions"])

    def test_icims_parser(self):
        html = """
        <span class="field-label">Job Location</span>
        <dt class="iCIMS_JobHeaderField">Are you willing to relocate?</dt>
        """
        res = extract_questions_from_html(html, "https://careers-company.icims.com/jobs/123")
        self.assertIn("Are you willing to relocate?", res["questions"])
        self.assertNotIn("Job Location", res["questions"])

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
        mock_extract.return_value = {
            "questions": ["Q1", "Q2"],
            "source": "test",
            "confidence": 0.9,
            "error": None,
        }

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
        self.assertEqual(response.json()["source"], "test")

    def test_routing_threshold_behavior(self):
        # High confidence, no fallback
        html_lever = "<html>"
        for i in range(20):
            html_lever += f"<div class='application-question'>Why do you want to work here {i}?</div>"
        html_lever += "</html>"
        res = extract_questions_from_html(html_lever, "jobs.lever.co", threshold=0.65)
        self.assertEqual(res["source"], "lever")
        self.assertGreaterEqual(res["confidence"], 0.65)
        
        # Low confidence, dynamic ATS indicator, forces fallback
        with patch("scrapers.playwright_fallback_extract") as mock_fallback:
            mock_fallback.return_value = {
                "questions": ["FallbackQ1"],
                "field_map": [{"label": "FallbackQ1", "name": "q1", "type": "text"}],
                "source": "playwright_fallback",
                "confidence": 0.9,
                "error": None
            }
            res2 = extract_questions_from_html("<html></html>", "https://company.wd1.myworkdayjobs.com/en-US/careers/job/123", threshold=0.65)
            self.assertEqual(res2["source"], "playwright_fallback")
            self.assertEqual(res2["questions"], ["FallbackQ1"])

    def test_noise_filtering(self):
        html = """
        <label>Attach Resume</label>
        <label>Enter Manually</label>
        <label>First Name</label>
        <label>Tell us about yourself?</label>
        """
        res = extract_questions_from_html(html, "https://example.com", threshold=0.0)
        self.assertNotIn("Attach Resume", res["questions"])
        self.assertNotIn("Enter Manually", res["questions"])
        self.assertNotIn("First Name", res["questions"])
        self.assertIn("Tell us about yourself?", res["questions"])

if __name__ == "__main__":
    unittest.main()
