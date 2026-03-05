import sys
from unittest.mock import MagicMock

# Mock out dependencies that are not in the environment
# to allow importing 'app' without errors.
sys.modules['fastapi'] = MagicMock()
sys.modules['fastapi.responses'] = MagicMock()
sys.modules['fastapi.staticfiles'] = MagicMock()
sys.modules['pydantic'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['dotenv'] = MagicMock()

import unittest
from unittest.mock import patch
import app

class TestCostEstimation(unittest.TestCase):
    def test_estimate_cost_normal(self):
        # Mock costs: $1.00 per 1M input, $2.00 per 1M output
        with patch("app.COST_INPUT_PER_1M", 1.0), \
             patch("app.COST_OUTPUT_PER_1M", 2.0):
            # 1M input, 1M output => 1.0 + 2.0 = 3.0
            self.assertAlmostEqual(app._estimate_cost(1_000_000, 1_000_000), 3.0)
            # 500k input, 250k output => 0.5 + 0.5 = 1.0
            self.assertAlmostEqual(app._estimate_cost(500_000, 250_000), 1.0)

    def test_estimate_cost_zero_costs(self):
        # Mock costs: $0.00
        with patch("app.COST_INPUT_PER_1M", 0.0), \
             patch("app.COST_OUTPUT_PER_1M", 0.0):
            self.assertEqual(app._estimate_cost(1_000_000, 1_000_000), 0.0)

    def test_estimate_cost_zero_tokens(self):
        # Mock costs: $1.00 per 1M
        with patch("app.COST_INPUT_PER_1M", 1.0), \
             patch("app.COST_OUTPUT_PER_1M", 1.0):
            self.assertEqual(app._estimate_cost(0, 0), 0.0)

    def test_estimate_cost_high_tokens(self):
        # Mock costs: $1.50 per 1M input, $3.50 per 1M output
        with patch("app.COST_INPUT_PER_1M", 1.5), \
             patch("app.COST_OUTPUT_PER_1M", 3.5):
            # 10M input => 15.0, 20M output => 70.0 => total 85.0
            self.assertAlmostEqual(app._estimate_cost(10_000_000, 20_000_000), 85.0)

if __name__ == "__main__":
    unittest.main()
