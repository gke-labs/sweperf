import unittest
import sys
import os

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(repo_root, "benchmark"))

import tempfile
import json
from process_metrics import parse_metrics, percentile, process_metrics, parse_job_metrics, process_job_metrics

class TestMetrics(unittest.TestCase):
    def test_parse_metrics(self):
        lines = [
            "2023-10-10T12:00:00Z node-1 100m 1024Mi 1",
            "2023-10-10T12:00:10Z node-1 200m 2048Mi 2",
            "2023-10-10T12:00:00Z node-2 500m 500Mi 1"
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

    def test_parse_job_metrics(self):
        data = {
            "items": [
                {
                    "metadata": {"creationTimestamp": "2023-10-10T12:00:00Z"},
                    "status": {
                        "startTime": "2023-10-10T12:00:05Z",
                        "containerStatuses": [{
                            "state": {
                                "terminated": {
                                    "finishedAt": "2023-10-10T12:01:05Z",
                                    "exitCode": 0
                                }
                            }
                        }]
                    }
                },
                {
                    "metadata": {"creationTimestamp": "2023-10-10T12:01:00Z"},
                    "status": {
                        "startTime": "2023-10-10T12:01:10Z",
                        "containerStatuses": [{
                            "state": {
                                "terminated": {
                                    "finishedAt": "2023-10-10T12:01:40Z",
                                    "exitCode": 1,
                                    "reason": "OOMKilled"
                                }
                            }
                        }]
                    }
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            json.dump(data, f)
            temp_name = f.name
            
        try:
            metrics = parse_job_metrics(temp_name)
            self.assertEqual(metrics["lengths"], [60.0, 30.0])
            self.assertEqual(metrics["pending_times"], [5.0, 10.0])
            self.assertEqual(metrics["succeeded"], 1)
            self.assertEqual(metrics["failed"], 1)
            self.assertEqual(metrics["oom_killed"], 1)
            self.assertEqual(metrics["other_errors"], 0)
        finally:
            os.remove(temp_name)

    def test_process_job_metrics(self):
        metrics = {
            'lengths': [60.0, 30.0],
            'pending_times': [5.0, 10.0],
            'earliest_start': None,
            'latest_end': None,
            'succeeded': 1,
            'failed': 1,
            'oom_killed': 1,
            'other_errors': 0,
        }
        report = process_job_metrics(metrics)
        self.assertIn("Completed Jobs:** 2", report)
        self.assertIn("Succeeded: 1", report)
        self.assertIn("Failed: 1", report)
        self.assertIn("OOMKilled: 1", report)
        self.assertIn("Avg: 45.0", report)
        self.assertIn("Time-to-Start", report)
        self.assertIn("Avg: 7.5", report)

if __name__ == "__main__":
    unittest.main()
