import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline_control import (
    TemporalSmoother,
    WorkerEventEngine,
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


def worker_observation(track_id=7, ppe_type="helmet", level="WARNING", frame_id=1):
    key = f"cam/run/{track_id}/{ppe_type}/NOT_WORN"
    return key, {
        "event_key": key,
        "camera_id": "cam",
        "run_id": "run",
        "frame_id": frame_id,
        "timestamp_ms": frame_id * 100,
        "track_id": track_id,
        "worker_key": f"cam/run/{track_id}",
        "active_zones": [],
        "alert_level": level,
        "violations": [f"no_{ppe_type}"],
        "conf": 0.9,
        "bbox": [0, 0, 100, 200],
        "ppe_type": ppe_type,
        "ppe_state": "NOT_WORN",
        "association_method": "CENTER_CONTAINMENT",
        "association_confidence": 0.9,
        "visibility": "VISIBLE",
        "reason_code": "NEGATIVE_LABEL_DETECTED",
    }


class TestWorkerEventEngine(unittest.TestCase):
    def test_two_workers_in_same_zone_remain_separate(self):
        engine = WorkerEventEngine(required_frames=1, cooldown_seconds=0)
        key_1, item_1 = worker_observation(track_id=1)
        key_2, item_2 = worker_observation(track_id=2)
        emitted = engine.process(
            {key_1: item_1, key_2: item_2},
            0.1,
            active_track_ids={1, 2},
        )
        self.assertEqual(len(emitted), 2)
        self.assertEqual({item["track_id"] for item in emitted}, {1, 2})
        self.assertTrue(all(item["event_action"] == "START" for item in emitted))

    def test_lost_track_does_not_end_or_duplicate_event(self):
        engine = WorkerEventEngine(required_frames=1, cooldown_seconds=0)
        key, item = worker_observation()
        started = engine.process({key: item}, 0.1, active_track_ids={7})
        self.assertEqual(started[0]["event_action"], "START")

        self.assertEqual(
            engine.process({}, 0.2, lost_track_ids={7}),
            [],
        )
        item["frame_id"] = 3
        item["timestamp_ms"] = 300
        self.assertEqual(
            engine.process({key: item}, 0.3, active_track_ids={7}),
            [],
        )

    def test_removed_track_ends_event(self):
        engine = WorkerEventEngine(required_frames=1, cooldown_seconds=0)
        key, item = worker_observation()
        engine.process({key: item}, 0.1, active_track_ids={7})
        ended = engine.process({}, 0.2, removed_track_ids={7})
        self.assertEqual(ended[0]["event_action"], "END")
        self.assertEqual(ended[0]["reason_code"], "TRACK_ENDED")

    def test_compliance_restored_ends_after_required_frames(self):
        engine = WorkerEventEngine(required_frames=2, cooldown_seconds=0)
        key, item = worker_observation(frame_id=1)
        engine.process({key: item}, 0.1, active_track_ids={7})
        started = engine.process({key: item}, 0.2, active_track_ids={7})
        self.assertEqual(started[0]["event_action"], "START")
        restored = {(7, "helmet"): "WORN"}
        self.assertEqual(
            engine.process(
                {}, 0.3, active_track_ids={7}, worker_ppe_states=restored
            ),
            [],
        )
        ended = engine.process(
            {}, 0.4, active_track_ids={7}, worker_ppe_states=restored
        )
        self.assertEqual(ended[0]["reason_code"], "COMPLIANCE_RESTORED")

    def test_unknown_ppe_does_not_end_active_event(self):
        engine = WorkerEventEngine(required_frames=1, cooldown_seconds=0)
        key, item = worker_observation()
        engine.process({key: item}, 0.1, active_track_ids={7})
        emitted = engine.process(
            {},
            0.2,
            active_track_ids={7},
            worker_ppe_states={(7, "helmet"): "UNKNOWN"},
        )
        self.assertEqual(emitted, [])
        self.assertTrue(engine.events[key]["active"])


if __name__ == "__main__":
    unittest.main()
