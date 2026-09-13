import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline_control import (
    TemporalSmoother,
    should_publish_live_frame,
    should_run_inference,
)


def alert(level, marker):
    return {
        "Z01": {
            "level": level,
            "log_data": {"alert_level": level, "marker": marker},
        }
    }


class TestTemporalSmoother(unittest.TestCase):
    def test_sustained_alert_emits_once(self):
        smoother = TemporalSmoother(required_frames=2, cooldown_seconds=5)

        self.assertEqual(smoother.process_alerts(alert("WARNING", 1), 0), [])
        emitted = smoother.process_alerts(alert("WARNING", 2), 1)
        self.assertEqual([item["marker"] for item in emitted], [2])

        self.assertEqual(smoother.process_alerts(alert("WARNING", 3), 2), [])
        self.assertEqual(smoother.process_alerts(alert("WARNING", 4), 10), [])

    def test_escalation_emits_immediately(self):
        smoother = TemporalSmoother(required_frames=2, cooldown_seconds=5)
        smoother.process_alerts(alert("WARNING", 1), 0)
        smoother.process_alerts(alert("WARNING", 2), 1)

        emitted = smoother.process_alerts(alert("CRITICAL", 3), 2)
        self.assertEqual([item["marker"] for item in emitted], [3])

    def test_normal_reset_rearms_after_cooldown(self):
        smoother = TemporalSmoother(required_frames=2, cooldown_seconds=5)
        smoother.process_alerts(alert("WARNING", 1), 0)
        smoother.process_alerts(alert("WARNING", 2), 1)

        smoother.process_alerts({}, 2)
        smoother.process_alerts({}, 3)

        self.assertEqual(smoother.process_alerts(alert("WARNING", 4), 4), [])
        self.assertEqual(smoother.process_alerts(alert("WARNING", 5), 4.5), [])
        emitted = smoother.process_alerts(alert("WARNING", 6), 6)
        self.assertEqual([item["marker"] for item in emitted], [6])


class TestInferenceSchedule(unittest.TestCase):
    def test_interval_three_runs_first_and_every_third_frame(self):
        scheduled = [
            frame_id
            for frame_id in range(1, 9)
            if should_run_inference(frame_id, 3)
        ]
        self.assertEqual(scheduled, [1, 4, 7])

    def test_non_positive_interval_falls_back_to_every_frame(self):
        self.assertTrue(all(should_run_inference(frame_id, 0) for frame_id in range(1, 5)))

    def test_live_preview_schedule_is_rate_limited(self):
        self.assertTrue(should_publish_live_frame(0.0, None, 10))
        self.assertFalse(should_publish_live_frame(0.05, 0.0, 10))
        self.assertTrue(should_publish_live_frame(0.1, 0.0, 10))
        self.assertFalse(should_publish_live_frame(1.0, None, 0))


if __name__ == "__main__":
    unittest.main()
