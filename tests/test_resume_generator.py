import unittest
from pathlib import Path
import json
import shutil
from jobs.resume_generator import generate_resume_for_job, score_bullet

class TestResumeGenerator(unittest.TestCase):
    def setUp(self):
        # We assume the profile and style files are present in the mock data, or we'll just test the pure functions.
        pass

    def test_score_bullet(self):
        jd_keywords = {"python", "react", "fast"}
        
        # Match python + metric
        b1 = "Built a backend in python that improved speed by 50%"
        self.assertEqual(score_bullet(b1, jd_keywords, True), 15) # 10 (metric) + 5 (python)
        
        # No match, no metric
        b2 = "Worked on frontend tasks"
        self.assertEqual(score_bullet(b2, jd_keywords, False), 0)
        
        # Match react and fast, no metric
        b3 = "Used react to make the app fast"
        self.assertEqual(score_bullet(b3, jd_keywords, False), 10) # 5 (react) + 5 (fast)

    def test_generate_resume(self):
        # Test artifact generation
        result = generate_resume_for_job("test_id_123", "TestCorp", "Test Engineer", "Python SQL metrics")
        
        self.assertEqual(result["job_id"], "test_id_123")
        self.assertEqual(result["status"], "generated")
        self.assertIn("score", result["metadata"])
        
        pdf_path = Path(result["pdf_path"])
        txt_path = Path(result["txt_path"])
        
        self.assertTrue(pdf_path.exists())
        self.assertTrue(txt_path.exists())
        
        # Clean up
        if pdf_path.exists():
            pdf_path.unlink()
        if txt_path.exists():
            txt_path.unlink()

if __name__ == '__main__':
    unittest.main()
