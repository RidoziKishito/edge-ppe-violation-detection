import csv
import json
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

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

    def test_start_snapshot_preserves_prepared_evidence_and_scene_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            logger = EdgeLogger(folder, filename="events.csv", run_id="run-1")
            frame = np.full((720, 1280, 3), 220, dtype=np.uint8)
            logger.log_event(
                {
                    "camera_id": "cam",
                    "run_id": "run-1",
                    "frame_id": 31,
                    "track_id": 4,
                    "worker_key": "cam/run-1/4",
                    "active_zones": [],
                    "alert_level": "WARNING",
                    "violations": ["no_helmet"],
                    "conf": 0.39,
                    "bbox": [164, 355, 343, 652],
                    "event_id": "evt-1",
                    "event_action": "START",
                    "event_status": "ACTIVE",
                    "ppe_type": "helmet",
                    "ppe_state": "NOT_WORN",
                    "confirmation_observations": 5,
                    "capture_snapshot": True,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "scene_workers": [
                        {
                            "track_id": 4,
                            "box": [164, 355, 343, 652],
                            "confidence": 0.9,
                            "violations": ["no_helmet"],
                        },
                        {
                            "track_id": 8,
                            "box": [600, 220, 760, 650],
                            "confidence": 0.8,
                            "violations": [],
                        },
                    ],
                },
                frame_img=frame,
            )
            with open(logger.filepath, encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            snapshot = cv2.imread(row["snapshot_path"])
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.shape[:2], frame.shape[:2])
            self.assertGreater(float(snapshot.mean()), 210)
            self.assertEqual(row["confirmation_observations"], "5")
            self.assertEqual(row["frame_width"], "1280")
            self.assertEqual(len(json.loads(row["scene_workers"])), 2)


if __name__ == "__main__":
    unittest.main()
