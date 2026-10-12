from uuid import uuid4

ALERT_SEVERITY = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


class TemporalSmoother:
    """Confirm alert transitions and emit only deduplicated zone events."""

    def __init__(self, required_frames=5, cooldown_seconds=5.0):
        self.required_frames = max(1, required_frames)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.zones_status = {}

    def process_alerts(self, current_frame_alerts, timestamp_seconds):
        valid_logs = []
        tracked_zones = set(self.zones_status).union(current_frame_alerts)

        for zone_id in tracked_zones:
            state = self.zones_status.setdefault(
                zone_id,
                {
                    "candidate_level": "NORMAL",
                    "candidate_count": 0,
                    "active_level": "NORMAL",
                    "last_trigger_at": None,
                },
            )
            current = current_frame_alerts.get(zone_id)
            current_level = current["level"] if current else "NORMAL"

            if current_level == state["candidate_level"]:
                state["candidate_count"] += 1
            else:
                state["candidate_level"] = current_level
                state["candidate_count"] = 1

            active_level = state["active_level"]
            if (
                current_level == "CRITICAL"
                and active_level == "WARNING"
            ):
                valid_logs.append(current["log_data"])
                state["active_level"] = "CRITICAL"
                state["last_trigger_at"] = timestamp_seconds
                continue

            if state["candidate_count"] < self.required_frames:
                continue

            if current_level == "NORMAL":
                state["active_level"] = "NORMAL"
                continue

            active_level = state["active_level"]
            is_new_alert = active_level == "NORMAL"
            is_escalation = (
                active_level != "NORMAL"
                and
                ALERT_SEVERITY[current_level] > ALERT_SEVERITY[active_level]
            )
            last_trigger = state["last_trigger_at"]
            cooldown_elapsed = (
                last_trigger is None
                or timestamp_seconds - last_trigger >= self.cooldown_seconds
            )

            if is_escalation or (is_new_alert and cooldown_elapsed):
                valid_logs.append(current["log_data"])
                state["active_level"] = current_level
                state["last_trigger_at"] = timestamp_seconds

        return valid_logs


class WorkerEventEngine:
    """Create deduplicated START/UPDATE/END events per worker and PPE."""

    def __init__(self, required_frames=5, cooldown_seconds=5.0):
        self.required_frames = max(1, int(required_frames))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.events = {}

    @staticmethod
    def _signature(observation):
        return (
            observation["alert_level"],
            tuple(zone["id"] for zone in observation.get("active_zones", [])),
            observation.get("ppe_state"),
            observation.get("reason_code"),
        )

    @staticmethod
    def _track_id(record):
        return int(record.get("track_id", -1))

    def _emit(self, state, action, observation, reason_code=None):
        record = dict(observation)
        frame_id = int(record["frame_id"])
        timestamp_ms = int(record.get("timestamp_ms", 0))
        if action == "START":
            state["event_id"] = f"evt_{uuid4().hex}"
            state["start_frame"] = frame_id
            state["start_timestamp_ms"] = timestamp_ms
        end_frame = frame_id if action == "END" else None
        duration_ms = max(0, timestamp_ms - state.get("start_timestamp_ms", timestamp_ms))
        record.update(
            event_id=state["event_id"],
            event_action=action,
            event_status="RESOLVED" if action == "END" else "ACTIVE",
            start_frame=state.get("start_frame"),
            end_frame=end_frame,
            duration_ms=duration_ms,
        )
        if reason_code:
            record["reason_code"] = reason_code
        return record

    def process(
        self,
        observations,
        timestamp_seconds,
        active_track_ids=None,
        lost_track_ids=None,
        removed_track_ids=None,
        worker_ppe_states=None,
        frame_id=None,
    ):
        active_track_ids = set(active_track_ids or ())
        lost_track_ids = set(lost_track_ids or ())
        removed_track_ids = set(removed_track_ids or ())
        worker_ppe_states = worker_ppe_states or {}
        emitted = []
        keys = set(self.events).union(observations)

        for key in keys:
            current = observations.get(key)
            state = self.events.setdefault(
                key,
                {
                    "candidate_count": 0,
                    "clear_count": 0,
                    "active": False,
                    "event_id": None,
                    "last_signature": None,
                    "last_observation": None,
                    "cooldown_until": 0.0,
                },
            )

            if current is not None:
                state["clear_count"] = 0
                state["last_observation"] = current
                signature = self._signature(current)
                if state["active"]:
                    if signature != state["last_signature"]:
                        emitted.append(self._emit(state, "UPDATE", current))
                        state["last_signature"] = signature
                    continue

                if timestamp_seconds < state["cooldown_until"]:
                    state["candidate_count"] = 0
                    continue

                state["candidate_count"] += 1
                if state["candidate_count"] >= self.required_frames:
                    state["active"] = True
                    state["candidate_count"] = 0
                    state["last_signature"] = signature
                    emitted.append(self._emit(state, "START", current))
                continue

            state["candidate_count"] = 0
            if not state["active"]:
                continue

            last = state["last_observation"]
            track_id = self._track_id(last)
            if track_id in lost_track_ids and track_id not in removed_track_ids:
                continue

            if track_id in removed_track_ids:
                reason = "TRACK_ENDED"
            elif track_id in active_track_ids:
                ppe_type = last.get("ppe_type")
                if ppe_type != "zone":
                    observed_state = worker_ppe_states.get(
                        (track_id, ppe_type), "UNKNOWN"
                    )
                    if observed_state != "WORN":
                        # Missing/uncertain evidence must not be interpreted as
                        # proof that the worker restored compliance.
                        continue
                state["clear_count"] += 1
                if state["clear_count"] < self.required_frames:
                    continue
                reason = (
                    "CONDITION_CLEARED"
                    if last.get("ppe_type") == "zone"
                    else "COMPLIANCE_RESTORED"
                )
            else:
                continue

            end_observation = dict(last)
            end_observation["frame_id"] = int(frame_id or last["frame_id"])
            end_observation["timestamp_ms"] = int(timestamp_seconds * 1000)
            emitted.append(self._emit(state, "END", end_observation, reason))
            state["active"] = False
            state["clear_count"] = 0
            state["last_signature"] = None
            state["cooldown_until"] = timestamp_seconds + self.cooldown_seconds

        return emitted

    def close_all(self, timestamp_seconds, frame_id, reason_code="RUN_ENDED"):
        """Resolve all active events when a video/run stops."""
        emitted = []
        for state in self.events.values():
            if not state["active"]:
                continue
            observation = dict(state["last_observation"])
            observation["frame_id"] = int(frame_id)
            observation["timestamp_ms"] = int(timestamp_seconds * 1000)
            emitted.append(self._emit(state, "END", observation, reason_code))
            state["active"] = False
        return emitted


def should_run_inference(frame_id, inference_interval):
    interval = max(1, inference_interval)
    return (frame_id - 1) % interval == 0


def should_publish_live_frame(timestamp_seconds, last_published_at, preview_fps):
    if preview_fps <= 0:
        return False
    if last_published_at is None:
        return True
    return timestamp_seconds - last_published_at >= 1.0 / preview_fps
