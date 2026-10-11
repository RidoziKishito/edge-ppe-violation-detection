import csv
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger import EdgeLogger


class TestEdgeLogger(unittest.TestCase):
    def test_worker_event_keeps_legacy_and_new_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            logger = EdgeLogger(folder, filename="events.csv", run_id="run-1")
            logger.log_event(
                {
                    "camera_id": "cam",
                    "run_id": "run-1",
                    "frame_id": 12,
                    "track_id": 7,
                    "worker_key": "cam/run-1/7",
                    "active_zones": [],
                    "alert_level": "WARNING",
                    "violations": ["no_helmet"],
                    "conf": 0.9,
                    "bbox": [0, 0, 100, 200],
                    "event_id": "evt-1",
                    "event_action": "START",
                    "event_status": "ACTIVE",
                    "ppe_type": "helmet",
                    "ppe_state": "NOT_WORN",
                    "association_method": "CENTER_CONTAINMENT",
                    "association_confidence": 0.9,
                    "visibility": "VISIBLE",
                    "reason_code": "NEGATIVE_LABEL_DETECTED",
                    "start_frame": 10,
                    "end_frame": None,
                    "duration_ms": 66,
                }
            )
            with open(logger.filepath, encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["violation_type"], "no_helmet")
            self.assertEqual(rows[0]["run_id"], "run-1")
            self.assertEqual(rows[0]["track_id"], "7")
            self.assertEqual(rows[0]["event_action"], "START")


if __name__ == "__main__":
    unittest.main()
