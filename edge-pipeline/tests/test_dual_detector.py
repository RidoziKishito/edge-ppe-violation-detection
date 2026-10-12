import os
import sys
import unittest
from unittest.mock import Mock

import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_infer


class FakeBox:
    def __init__(self, xyxy, confidence, class_id):
        self.xyxy = np.asarray([xyxy], dtype=np.float32)
        self.conf = np.asarray([confidence], dtype=np.float32)
        self.cls = np.asarray([class_id], dtype=np.float32)


class DualDetectorTests(unittest.TestCase):
    def test_person_detector_requests_only_person_and_normalizes_label(self):
        model = Mock()
        model.names = {0: "person", 1: "bicycle"}
        model.return_value = [Mock(boxes=[FakeBox((1, 2, 30, 80), 0.86, 0)])]

        people = edge_infer.infer_person_detections(
            model, np.zeros((100, 100, 3), dtype=np.uint8), 0.2, 0.45
        )

        self.assertEqual(people[0]["class_name"], "Person")
        self.assertEqual(people[0]["box"], (1, 2, 30, 80))
        self.assertAlmostEqual(people[0]["conf"], 0.86, places=5)
        self.assertEqual(model.call_args.kwargs["classes"], [0])
        self.assertEqual(model.call_args.kwargs["conf"], 0.1)

    def test_ppe_detector_ignores_its_weak_person_class(self):
        model = Mock()
        model.names = {0: "helmet", 6: "Person", 7: "no_helmet"}
        model.return_value = [
            Mock(
                boxes=[
                    FakeBox((10, 10, 20, 20), 0.9, 0),
                    FakeBox((0, 0, 80, 100), 0.7, 6),
                    FakeBox((12, 12, 22, 22), 0.8, 7),
                ]
            )
        ]

        detections = edge_infer.infer_ppe_detections(
            model, np.zeros((100, 100, 3), dtype=np.uint8), 0.4, 0.45
        )

        self.assertEqual(
            [item["class_name"] for item in detections], ["helmet", "no_helmet"]
        )
        self.assertEqual(model.call_args.kwargs["classes"], [0, 7])


if __name__ == "__main__":
    unittest.main()
