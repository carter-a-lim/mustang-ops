import unittest
from resume_gen import extract_keywords, score_bullet, generate_resume_variant

class TestResumeGen(unittest.TestCase):
    def test_extract_keywords(self):
        jd = "Seeking a Software Engineer with React and Python experience."
        keywords = extract_keywords(jd)
        self.assertIn("software", keywords)
        self.assertIn("engineer", keywords)
        self.assertIn("react", keywords)
        self.assertIn("python", keywords)
        # Verify stop words are removed
        self.assertNotIn("with", keywords)
        self.assertNotIn("and", keywords)

    def test_score_bullet_keyword_match(self):
        bullet = {
            "text": "Developed a web app using React and Node.js",
            "tags": ["React", "JavaScript"],
            "metric": None
        }
        jd_keywords = ["react", "node"]
        score = score_bullet(bullet, jd_keywords)
        # React matches in text (1.0) and tags (2.0)
        # Node matches in text (1.0)
        # Total should be 4.0
        self.assertEqual(score, 4.0)

    def test_score_bullet_with_metric(self):
        bullet = {
            "text": "Improved performance",
            "tags": [],
            "metric": "40% faster"
        }
        jd_keywords = ["performance"]
        score = score_bullet(bullet, jd_keywords)
        # Performance matches in text (1.0)
        # Metric boost (5.0)
        # Total should be 6.0
        self.assertEqual(score, 6.0)

    def test_generate_resume_variant_constraints(self):
        profile = {
            "profile": {
                "experience": [
                    {
                        "company": "Test Co",
                        "bullet_bank": [
                            {"text": "B1", "tags": ["T1"], "metric": "M1"},
                            {"text": "B2", "tags": ["T2"], "metric": "M2"},
                            {"text": "B3", "tags": ["T3"], "metric": "M3"},
                            {"text": "B4", "tags": ["T4"], "metric": "M4"}
                        ]
                    }
                ],
                "projects": []
            }
        }
        jd = "Looking for T1 and T2"
        # max_bullets_per_entry=2
        variant = generate_resume_variant(profile, jd, max_bullets_per_entry=2)

        exp = variant["experience"][0]
        self.assertEqual(len(exp["bullets"]), 2)
        # B1 and B2 should be chosen due to tag matches
        self.assertIn("B1", exp["bullets"])
        self.assertIn("B2", exp["bullets"])
        self.assertEqual(len(exp["dropped_bullets"]), 2)

    def test_generate_resume_variant_total_budget(self):
        profile = {
            "profile": {
                "experience": [
                    {
                        "company": "E1",
                        "bullet_bank": [{"text": "B1", "tags": ["match"], "metric": "M1"}]
                    },
                    {
                        "company": "E2",
                        "bullet_bank": [{"text": "B2", "tags": ["match"], "metric": "M2"}]
                    }
                ],
                "projects": [
                    {
                        "name": "P1",
                        "bullet_bank": [{"text": "B3", "tags": ["match"], "metric": "M3"}]
                    }
                ]
            }
        }
        jd = "match"
        # total_bullet_limit=2
        variant = generate_resume_variant(profile, jd, total_bullet_limit=2)

        total_bullets = len(variant["experience"][0]["bullets"]) + \
                        len(variant["experience"][1]["bullets"]) + \
                        len(variant["projects"][0]["bullets"])

        self.assertEqual(total_bullets, 2)

if __name__ == "__main__":
    unittest.main()
