import importlib.util
import os
import sys
import unittest

import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from person_tracker import DEFAULT_TRACK_BUFFER, PersonTracker


@unittest.skipUnless(importlib.util.find_spec("lap"), "ByteTrack dependency is not installed")
class TestPersonTracker(unittest.TestCase):
    def test_default_buffer_is_sixty_tracker_updates(self):
        tracker = PersonTracker()

        self.assertEqual(tracker.track_buffer, DEFAULT_TRACK_BUFFER)
        self.assertEqual(DEFAULT_TRACK_BUFFER, 60)

    def test_low_confidence_detection_recovers_existing_track(self):
        tracker = PersonTracker(
            track_high_thresh=0.25,
            track_low_thresh=0.1,
            new_track_thresh=0.25,
        )
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        strong_detection = {
            "box": (10, 10, 110, 210),
            "conf": 0.9,
            "class_name": "Person",
        }
        weak_detection = {
            "box": (12, 10, 112, 210),
            "conf": 0.15,
            "class_name": "Person",
        }

        first = tracker.update([strong_detection], frame)
        recovered = tracker.update([weak_detection], frame)

        self.assertEqual(len(recovered.active), 1)
        self.assertEqual(
            recovered.active[0]["track_id"], first.active[0]["track_id"]
        )
        self.assertEqual(recovered.lost_track_ids, set())

        weak_only_tracker = PersonTracker(
            track_high_thresh=0.25,
            track_low_thresh=0.1,
            new_track_thresh=0.25,
        )
        weak_only = weak_only_tracker.update([weak_detection], frame)
        self.assertEqual(weak_only.active, [])

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
