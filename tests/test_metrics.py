import unittest
import sys
import os

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(repo_root, "benchmark"))

from process_metrics import parse_metrics, percentile, process_metrics

class TestMetrics(unittest.TestCase):
    def test_parse_metrics(self):
        lines = [
            "node-1 100m 2% 1024Mi 10%",
            "node-1 200m 4% 2Gi 20%",
            "node-2 500m 10% 500Mi 5%"
        ]
        data = parse_metrics(lines)
        self.assertEqual(data["node-1"]["cpu"], [100, 200])
        self.assertEqual(data["node-1"]["ram"], [1024, 2048])
        self.assertEqual(data["node-2"]["cpu"], [500])
        self.assertEqual(data["node-2"]["ram"], [500])

    def test_percentile(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual(percentile(data, 0.9), 9.1)

    def test_process_metrics(self):
        data = {
            "node-1": {
                "cpu": [100, 200],
                "ram": [1024, 2048]
            }
        }
        report = process_metrics(data)
        self.assertIn("**Node:** `node-1`", report)
        self.assertIn("Avg: 150.0", report)
        self.assertIn("Max: 200", report)

if __name__ == "__main__":
    unittest.main()
