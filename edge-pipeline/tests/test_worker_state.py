import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rule_engine
import worker_state


def person(track_id, box=(0, 0, 100, 200)):
    return {
        "track_id": track_id,
        "track_status": "CONFIRMED",
        "box": box,
        "conf": 0.9,
        "class_name": "Person",
    }


def ppe(class_name, box=(20, 10, 40, 30), conf=0.8):
    return {"class_name": class_name, "box": box, "conf": conf}


class TestWorkerState(unittest.TestCase):
    def test_negative_label_builds_not_worn_state(self):
        states, unassigned = worker_state.build_worker_states(
            [person(7)],
            [ppe("no_helmet")],
            {"zones": []},
            "cam",
            "run",
            10,
            300,
        )
        self.assertEqual(unassigned, [])
        self.assertEqual(states[0]["worker_key"], "cam/run/7")
        self.assertEqual(states[0]["ppe"]["helmet"]["state"], "NOT_WORN")
        self.assertEqual(worker_state.state_violations(states[0]), ["no_helmet"])

    def test_missing_no_vest_label_remains_unknown(self):
        states, _ = worker_state.build_worker_states(
            [person(7)], [], {"zones": []}, "cam", "run", 10, 300
        )
        self.assertEqual(states[0]["ppe"]["vest"]["state"], "UNKNOWN")

    def test_conflicting_positive_and_negative_evidence_is_unknown(self):
        states, _ = worker_state.build_worker_states(
            [person(7)],
            [ppe("helmet"), ppe("no_helmet", conf=0.9)],
            {"zones": []},
            "cam",
            "run",
            10,
            300,
        )
        helmet = states[0]["ppe"]["helmet"]
        self.assertEqual(helmet["state"], "UNKNOWN")
        self.assertEqual(helmet["reason_code"], "CONFLICTING_EVIDENCE")

    def test_overlapping_people_do_not_share_one_ppe_detection(self):
        assignments, unassigned = rule_engine.associate_ppe_detections(
            [person(1), person(2, (10, 0, 110, 200))],
            [ppe("no_helmet", (20, 10, 40, 30))],
        )
        self.assertEqual(assignments[1], [])
        self.assertEqual(assignments[2], [])
        self.assertEqual(unassigned[0]["reason_code"], "AMBIGUOUS_OWNER")


if __name__ == "__main__":
    unittest.main()
