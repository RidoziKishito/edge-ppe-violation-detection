import csv
import os
import cv2
from datetime import datetime


class EdgeLogger:
    def __init__(self, log_dir="logs", source_name="video", filename=None):
        self.log_dir = log_dir
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
            writer.writerow(
                [
                    "timestamp",
                    "camera_id",
                    "frame_id",
                    "zone_id",
                    "alert_level",
                    "violation_type",
                    "confidence",
                    "bbox",
                    "snapshot_path",
                ]
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

        # Join zone list and violations into strings (e.g. "Z01|Z02", "no_helmet|no_gloves")
        zone_str = "|".join([z["id"] for z in active_zones]) if active_zones else "None"
        viol_str = "|".join(violations) if violations else "None"
        bbox_str = f"[{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]"

        snapshot_path = "None"
        # HANDLE SAVING SNAPSHOT IMAGE
        if frame_img is not None:
            # Create snapshots subdirectory
            snap_dir = os.path.join(self.log_dir, "snapshots")
            if not os.path.exists(snap_dir):
                os.makedirs(snap_dir)

            # Name snapshot using camera, frame and timestamp
            safe_time = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            snapshot_filename = f"snap_cam{camera_id}_f{frame_id}_{safe_time}.jpg"
            snapshot_path = os.path.join(snap_dir, snapshot_filename)

            # Write image file to disk
            cv2.imwrite(snapshot_path, frame_img)

        # Append a new row to the CSV log
        with open(self.filepath, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    timestamp,
                    camera_id,
                    frame_id,
                    zone_str,
                    alert_level,
                    viol_str,
                    conf,
                    bbox_str,
                    snapshot_path,
                ]
            )
