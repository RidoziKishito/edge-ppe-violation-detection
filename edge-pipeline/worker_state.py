"""Build worker-centric runtime state from tracked people and PPE detections."""

from __future__ import annotations

import rule_engine


PPE_SPECS = {
    "helmet": {
        "positive": "helmet",
        "negative": "no_helmet",
        "expected_region": "HEAD",
    },
    "vest": {
        "positive": "vest",
        "negative": "no_vest",
        "expected_region": "TORSO",
    },
}


def _best(items):
    return max(items, key=lambda item: float(item.get("conf", 0.0)), default=None)


def _ppe_record(ppe_type, detections):
    spec = PPE_SPECS[ppe_type]
    positive = _best(
        [item for item in detections if item["class_name"].lower() == spec["positive"]]
    )
    negative = _best(
        [
            item
            for item in detections
            if spec["negative"]
            and item["class_name"].lower() == spec["negative"]
        ]
    )

    if positive and negative:
        evidence = positive if positive["conf"] >= negative["conf"] else negative
        state = "UNKNOWN"
        reason_code = "CONFLICTING_EVIDENCE"
    elif negative:
        evidence = negative
        state = "NOT_WORN"
        reason_code = "NEGATIVE_LABEL_DETECTED"
    elif positive:
        evidence = positive
        state = "WORN"
        reason_code = "POSITIVE_LABEL_DETECTED"
    else:
        evidence = None
        state = "UNKNOWN"
        reason_code = "NO_PPE_EVIDENCE"

    return {
        "ppe_type": ppe_type,
        "expected_region": spec["expected_region"],
        "state": state,
        "evidence_class": evidence["class_name"] if evidence else None,
        "evidence_box": list(evidence["box"]) if evidence else None,
        "confidence": float(evidence["conf"]) if evidence else 0.0,
        "visibility": "VISIBLE" if evidence else "UNKNOWN",
        "association_method": "CENTER_CONTAINMENT" if evidence else "UNASSIGNED",
        "association_confidence": float(evidence["conf"]) if evidence else 0.0,
        "reason_code": reason_code,
    }


def build_worker_states(
    tracked_persons,
    ppe_detections,
    zones_config,
    camera_id,
    run_id,
    frame_id,
    timestamp_ms,
):
    """Return WorkerState records and PPE evidence without a valid owner."""
    assignments, unassigned = rule_engine.associate_ppe_detections(
        tracked_persons, ppe_detections
    )
    states = []
    for person in tracked_persons:
        x1, _y1, x2, y2 = person["box"]
        foot_point = ((x1 + x2) // 2, y2)
        active_zones = rule_engine.get_person_zones(foot_point, zones_config)
        track_id = int(person["track_id"])
        associated = assignments.get(track_id, [])
        worker_key = f"{camera_id}/{run_id}/{track_id}"
        states.append(
            {
                "schema_version": "1.0",
                "worker_key": worker_key,
                "camera_id": camera_id,
                "run_id": run_id,
                "frame_id": int(frame_id),
                "timestamp_ms": int(timestamp_ms),
                "track_id": track_id,
                "track_status": person.get("track_status", "CONFIRMED"),
                "person": {
                    "box": list(person["box"]),
                    "confidence": float(person["conf"]),
                    "foot_point": list(foot_point),
                },
                "zone_ids": [zone["id"] for zone in active_zones],
                "active_zones": active_zones,
                "ppe": {
                    ppe_type: _ppe_record(ppe_type, associated)
                    for ppe_type in PPE_SPECS
                },
            }
        )
    return states, unassigned


def state_violations(state):
    """Return explicit negative detector labels for one WorkerState."""
    return [
        record["evidence_class"]
        for record in state["ppe"].values()
        if record["state"] == "NOT_WORN" and record["evidence_class"]
    ]


def worker_observations(states):
    """Convert WorkerState records into per-worker/per-PPE event observations."""
    observations = {}
    for state in states:
        violations = state_violations(state)
        alert_level = rule_engine.classify_alert(state["active_zones"], violations)
        for ppe_type, record in state["ppe"].items():
            if record["state"] != "NOT_WORN":
                continue
            key = (
                f'{state["worker_key"]}/{ppe_type}/NOT_WORN'
            )
            observations[key] = {
                "event_key": key,
                "camera_id": state["camera_id"],
                "run_id": state["run_id"],
                "frame_id": state["frame_id"],
                "timestamp_ms": state["timestamp_ms"],
                "track_id": state["track_id"],
                "worker_key": state["worker_key"],
                "active_zones": state["active_zones"],
                "alert_level": alert_level,
                "violations": [record["evidence_class"]],
                "conf": record["confidence"],
                "bbox": state["person"]["box"],
                "ppe_type": ppe_type,
                "ppe_state": record["state"],
                "association_method": record["association_method"],
                "association_confidence": record["association_confidence"],
                "visibility": record["visibility"],
                "reason_code": record["reason_code"],
            }

        if not violations and state["active_zones"]:
            key = f'{state["worker_key"]}/zone/ZONE_PRESENCE'
            observations[key] = {
                "event_key": key,
                "camera_id": state["camera_id"],
                "run_id": state["run_id"],
                "frame_id": state["frame_id"],
                "timestamp_ms": state["timestamp_ms"],
                "track_id": state["track_id"],
                "worker_key": state["worker_key"],
                "active_zones": state["active_zones"],
                "alert_level": rule_engine.classify_alert(
                    state["active_zones"], []
                ),
                "violations": [],
                "conf": state["person"]["confidence"],
                "bbox": state["person"]["box"],
                "ppe_type": "zone",
                "ppe_state": "ZONE_PRESENCE",
                "association_method": "FOOT_POINT_IN_POLYGON",
                "association_confidence": state["person"]["confidence"],
                "visibility": "VISIBLE",
                "reason_code": "WORKER_IN_SAFETY_ZONE",
            }
    return observations
