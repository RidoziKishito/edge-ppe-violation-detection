import csv
import json
import os
import cv2
from datetime import datetime


class EdgeLogger:
    FIELDNAMES = [
        "timestamp",
        "camera_id",
        "frame_id",
        "zone_id",
        "alert_level",
        "violation_type",
        "confidence",
        "bbox",
        "snapshot_path",
        "schema_version",
        "run_id",
        "event_id",
        "event_action",
        "event_status",
        "track_id",
        "worker_key",
        "ppe_type",
        "ppe_state",
        "association_method",
        "association_confidence",
        "visibility",
        "reason_code",
        "start_frame",
        "end_frame",
        "duration_ms",
        "confirmation_observations",
        "frame_width",
        "frame_height",
        "scene_workers",
    ]

    def __init__(self, log_dir="logs", source_name="video", filename=None, run_id=None):
        self.log_dir = log_dir
        self.run_id = run_id or "legacy"
        # Automatically create logs directory if it does not exist
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        if filename:
            self.filepath = os.path.join(self.log_dir, filename)
        else:
            date_str = datetime.now().strftime("%Y%m%d")
            base_filename = f"{date_str}_violations_{source_name}"
            idx = 0
            while True:
                suffix = f"_{idx}" if idx > 0 else ""
                self.filepath = os.path.join(
                    self.log_dir, f"{base_filename}{suffix}.csv"
                )
                if not os.path.exists(self.filepath):
                    break
                idx += 1

        # Create CSV header
        with open(self.filepath, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.FIELDNAMES)

    def _save_snapshot(self, camera_id, frame_id, frame_img):
        if frame_img is None:
            return "None"
        snap_dir = os.path.join(self.log_dir, "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        safe_time = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        snapshot_filename = f"snap_cam{camera_id}_f{frame_id}_{safe_time}.jpg"
        snapshot_path = os.path.join(snap_dir, snapshot_filename)
        cv2.imwrite(snapshot_path, frame_img)
        return snapshot_path

    def _save_event_snapshot(self, event, frame_img):
        """Save the prepared recap evidence for the worker that started the alert."""
        if frame_img is None or not event.get("capture_snapshot"):
            return "None"
        evidence = frame_img.copy()
        return self._save_snapshot(
            event.get("camera_id", "unknown"),
            event.get("frame_id", 0),
            evidence,
        )

    def _append(self, row):
        with open(self.filepath, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writerow({field: row.get(field, "") for field in self.FIELDNAMES})

    def log_event(self, event, frame_img=None):
        """Write one START/UPDATE/END worker event while preserving legacy columns."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        zones = event.get("active_zones", [])
        violations = event.get("violations", [])
        box = event.get("bbox", [])
        snapshot = self._save_event_snapshot(event, frame_img)
        self._append(
            {
                "timestamp": timestamp,
                "camera_id": event.get("camera_id", "unknown"),
                "frame_id": event.get("frame_id", 0),
                "zone_id": "|".join(zone["id"] for zone in zones) if zones else "None",
                "alert_level": event.get("alert_level", "NORMAL"),
                "violation_type": "|".join(violations) if violations else "None",
                "confidence": event.get("conf", 0.0),
                "bbox": str(list(box)) if box else "None",
                "snapshot_path": snapshot,
                "schema_version": "1.0",
                "run_id": event.get("run_id", self.run_id),
                "event_id": event.get("event_id"),
                "event_action": event.get("event_action"),
                "event_status": event.get("event_status"),
                "track_id": event.get("track_id"),
                "worker_key": event.get("worker_key"),
                "ppe_type": event.get("ppe_type"),
                "ppe_state": event.get("ppe_state"),
                "association_method": event.get("association_method"),
                "association_confidence": event.get("association_confidence"),
                "visibility": event.get("visibility"),
                "reason_code": event.get("reason_code"),
                "start_frame": event.get("start_frame"),
                "end_frame": event.get("end_frame"),
                "duration_ms": event.get("duration_ms"),
                "confirmation_observations": event.get(
                    "confirmation_observations"
                ),
                "frame_width": event.get("frame_width"),
                "frame_height": event.get("frame_height"),
                "scene_workers": json.dumps(
                    event.get("scene_workers", []), separators=(",", ":")
                ),
            }
        )

    def log_violation(
        self,
        camera_id,
        frame_id,
        active_zones,
        alert_level,
        violations,
        conf,
        bbox,
        frame_img=None,
    ):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Join zone list and V2 violations into strings (e.g. "Z01|Z02", "no_helmet|no_vest")
        zone_str = "|".join([z["id"] for z in active_zones]) if active_zones else "None"
        viol_str = "|".join(violations) if violations else "None"
        bbox_str = f"[{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]"

        snapshot_path = self._save_snapshot(camera_id, frame_id, frame_img)
        self._append(
            {
                "timestamp": timestamp,
                "camera_id": camera_id,
                "frame_id": frame_id,
                "zone_id": zone_str,
                "alert_level": alert_level,
                "violation_type": viol_str,
                "confidence": conf,
                "bbox": bbox_str,
                "snapshot_path": snapshot_path,
                "schema_version": "1.0",
                "run_id": self.run_id,
                "event_action": "START",
                "event_status": "ACTIVE",
            }
        )
