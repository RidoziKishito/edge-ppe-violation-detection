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


def should_run_inference(frame_id, inference_interval):
    interval = max(1, inference_interval)
    return (frame_id - 1) % interval == 0


def should_publish_live_frame(timestamp_seconds, last_published_at, preview_fps):
    if preview_fps <= 0:
        return False
    if last_published_at is None:
        return True
    return timestamp_seconds - last_published_at >= 1.0 / preview_fps
