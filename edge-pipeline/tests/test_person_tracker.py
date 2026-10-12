import importlib.util
import os
import sys
import unittest

import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from person_tracker import PersonTracker


@unittest.skipUnless(importlib.util.find_spec("lap"), "ByteTrack dependency is not installed")
class TestPersonTracker(unittest.TestCase):
    def test_track_id_persists_and_reports_lifecycle(self):
        tracker = PersonTracker(track_buffer=2)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        detection = {
            "box": (10, 10, 110, 210),
            "conf": 0.9,
            "class_name": "Person",
        }

        first = tracker.update([detection], frame)
        second = tracker.update([detection], frame)
        self.assertEqual(first.active[0]["track_id"], second.active[0]["track_id"])

        lost = tracker.update([], frame)
        self.assertEqual(lost.lost_track_ids, {first.active[0]["track_id"]})

        tracker.update([], frame)
        removed = tracker.update([], frame)
        self.assertEqual(removed.removed_track_ids, {first.active[0]["track_id"]})


if __name__ == "__main__":
    unittest.main()
