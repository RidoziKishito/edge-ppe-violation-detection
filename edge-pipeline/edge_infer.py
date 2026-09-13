import argparse
import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path

import cv2
from ultralytics import YOLO

import display
import rule_engine
from logger import EdgeLogger
from pipeline_control import (
    ALERT_SEVERITY,
    TemporalSmoother,
    should_publish_live_frame,
    should_run_inference,
)


VIOLATION_CLASSES = {
    "no_helmet",
    "no_goggle",
    "no_gloves",
    "no_boots",
    "none",
}


def load_zones(zones_path):
    try:
        with open(zones_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        print("Warning: zones.json not found, running without zones.")
        return {"zones": []}


def validate_zone_profile(zones_config, width, height):
    profile_width = zones_config.get("width")
    profile_height = zones_config.get("height")
    if profile_width and profile_height:
        if int(profile_width) != width or int(profile_height) != height:
            raise ValueError(
                "Zone profile resolution "
                f"{profile_width}x{profile_height} does not match video "
                f"resolution {width}x{height}."
            )


def infer_detections(model, frame, conf_thres, iou_thres):
    persons = []
    other_detections = []
    results = model(
        frame,
        stream=True,
        verbose=False,
        conf=conf_thres,
        iou=iou_thres,
    )

    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = math.ceil(float(box.conf[0]) * 100) / 100
            class_name = model.names[int(box.cls[0])]
            detection = {
                "box": (x1, y1, x2, y2),
                "conf": confidence,
                "class_name": class_name,
            }
            if class_name.lower() == "person":
                persons.append(detection)
            else:
                other_detections.append(detection)

    return persons, other_detections


def keep_highest_alert(current_frame_alerts, zone_id, alert):
    existing_level = current_frame_alerts.get(zone_id, {}).get("level", "NORMAL")
    if ALERT_SEVERITY[alert["level"]] > ALERT_SEVERITY[existing_level]:
        current_frame_alerts[zone_id] = alert


def build_alert(
    camera_id,
    frame_id,
    active_zones,
    alert_level,
    violations,
    confidence,
    box,
):
    return {
        "level": alert_level,
        "log_data": {
            "camera_id": camera_id,
            "frame_id": frame_id,
            "active_zones": active_zones,
            "alert_level": alert_level,
            "violations": violations,
            "conf": confidence,
            "bbox": box,
        },
    }


def evaluate_detections(
    frame,
    persons,
    other_detections,
    zones_config,
    camera_id,
    frame_id,
):
    current_frame_alerts = {}

    for person in persons:
        x1, _, x2, y2 = person["box"]
        center_point = ((x1 + x2) // 2, y2)
        active_zones = rule_engine.get_person_zones(center_point, zones_config)
        violations = rule_engine.check_ppe_violation(
            person["box"], other_detections
        )
        alert_level = rule_engine.classify_alert(active_zones, violations)
        zone_id = (
            "|".join(zone["id"] for zone in active_zones)
            if active_zones
            else "NO_ZONE"
        )

        if alert_level != "NORMAL":
            keep_highest_alert(
                current_frame_alerts,
                zone_id,
                build_alert(
                    camera_id,
                    frame_id,
                    active_zones,
                    alert_level,
                    violations,
                    person["conf"],
                    person["box"],
                ),
            )
        display.draw_person_alert(
            frame,
            person["box"],
            center_point,
            alert_level,
            violations,
        )

    debug_draw_only = []
    for detection in other_detections:
        x1, _, x2, y2 = detection["box"]
        center_point = ((x1 + x2) // 2, y2)
        if any(
            person["box"][0] <= center_point[0] <= person["box"][2]
            and person["box"][1] <= center_point[1] <= person["box"][3]
            for person in persons
        ):
            continue

        active_zones = rule_engine.get_person_zones(center_point, zones_config)
        class_name = detection["class_name"]
        violations = (
            [class_name] if class_name.lower() in VIOLATION_CLASSES else []
        )
        alert_level = rule_engine.classify_alert(active_zones, violations)

        if alert_level == "NORMAL":
            debug_draw_only.append(detection)
            continue

        zone_id = (
            "|".join(zone["id"] for zone in active_zones)
            if active_zones
            else "NO_ZONE"
        )
        keep_highest_alert(
            current_frame_alerts,
            zone_id,
            build_alert(
                camera_id,
                frame_id,
                active_zones,
                alert_level,
                violations,
                detection["conf"],
                detection["box"],
            ),
        )
        display.draw_person_alert(
            frame,
            detection["box"],
            center_point,
            alert_level,
            violations,
        )

    display.draw_other_detections(frame, debug_draw_only)
    return current_frame_alerts


def encode_live_frame(frame):
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, 82],
    )
    if not ok:
        return None
    return encoded.tobytes()


def write_live_frame(frame_bytes, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(frame_bytes)
    try:
        os.replace(temporary, destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        return False
    return True


def publish_live_frame(frame, destination):
    frame_bytes = encode_live_frame(frame)
    if frame_bytes is None:
        return False
    return write_live_frame(frame_bytes, destination)


def push_live_frame(frame_bytes, push_url, timeout=0.2):
    if not push_url:
        return False
    request = urllib.request.Request(
        push_url,
        data=frame_bytes,
        headers={"Content-Type": "image/jpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def run_pipeline(
    model_path,
    source,
    conf_thres,
    iou_thres,
    classes_path,
    zones_path,
    smooth_frames,
    log_dir="logs",
    output_path=None,
    headless=False,
    max_frames=None,
    camera_id=None,
    inference_interval=1,
    alert_cooldown=5.0,
    live_frame_path=None,
    live_preview_fps=20.0,
    frame_push_url=None,
):
    del classes_path  # Kept for CLI compatibility.
    model = YOLO(model_path)
    zones_config = load_zones(zones_path)

    video_source = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"Error: Could not open video source: {source}")
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    validate_zone_profile(zones_config, width, height)

    out_path = output_path or str(Path(str(source)).with_suffix("")) + "_output.mp4"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        out_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    window_name = "Trinity Edge - Safety Pipeline"
    if not headless:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    source_name = os.path.splitext(os.path.basename(str(source)))[0]
    resolved_camera_id = camera_id or source_name
    safety_logger = EdgeLogger(
        log_dir=log_dir,
        source_name=source_name,
        filename="events.csv" if Path(log_dir).name != "logs" else None,
    )
    smoother = TemporalSmoother(
        required_frames=smooth_frames,
        cooldown_seconds=alert_cooldown,
    )
    cached_persons = []
    cached_other_detections = []
    last_live_frame_at = None
    frame_push_failures = 0
    frame_id = 0

    last_zones_mtime = 0
    if Path(zones_path).exists():
        last_zones_mtime = Path(zones_path).stat().st_mtime

    print(
        "Running video stream. "
        f"Smoothing={smooth_frames}, inference interval={inference_interval}, "
        f"alert cooldown={alert_cooldown}s. Press 'q' or 'X' to exit."
    )

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_id += 1
        if max_frames and frame_id > max_frames:
            break

        # Check for zone updates every ~1 second
        if frame_id % int(fps) == 0 and Path(zones_path).exists():
            current_mtime = Path(zones_path).stat().st_mtime
            if current_mtime > last_zones_mtime:
                print(f"Zones config changed. Reloading from {zones_path}...")
                zones_config = load_zones(zones_path)
                validate_zone_profile(zones_config, width, height)
                last_zones_mtime = current_mtime

        inference_frame = should_run_inference(frame_id, inference_interval)
        if inference_frame:
            cached_persons, cached_other_detections = infer_detections(
                model,
                frame,
                conf_thres,
                iou_thres,
            )

        display.draw_zones(frame, zones_config)
        current_frame_alerts = evaluate_detections(
            frame,
            cached_persons,
            cached_other_detections,
            zones_config,
            resolved_camera_id,
            frame_id,
        )

        if inference_frame:
            video_time_seconds = (frame_id - 1) / fps
            valid_logs = smoother.process_alerts(
                current_frame_alerts,
                video_time_seconds,
            )
            for log_data in valid_logs:
                log_data["frame_img"] = frame
                safety_logger.log_violation(**log_data)

        video_time_seconds = (frame_id - 1) / fps
        if (live_frame_path or frame_push_url) and should_publish_live_frame(
            video_time_seconds,
            last_live_frame_at,
            live_preview_fps,
        ):
            frame_bytes = encode_live_frame(frame)
            if frame_bytes is not None:
                if live_frame_path:
                    write_live_frame(frame_bytes, live_frame_path)
                if frame_push_url and frame_push_failures < 3:
                    if push_live_frame(frame_bytes, frame_push_url):
                        frame_push_failures = 0
                    else:
                        frame_push_failures += 1
                last_live_frame_at = video_time_seconds

        writer.write(frame)
        if not headless:
            cv2.imshow(window_name, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_AUTOSIZE) == -1:
                    break
            except cv2.error:
                break

    cap.release()
    writer.release()
    if not headless:
        cv2.destroyAllWindows()
    print(f"Output video saved to: {out_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="best.onnx")
    parser.add_argument("--source", default="0")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--class-names", default="configs/ppe_classes.txt")
    parser.add_argument("--zones", default="configs/zones.json")
    parser.add_argument("--smooth", type=int, default=5)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--output")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--camera-id")
    parser.add_argument("--inference-interval", type=int, default=1)
    parser.add_argument("--alert-cooldown", type=float, default=5.0)
    parser.add_argument("--live-frame")
    parser.add_argument("--live-preview-fps", type=float, default=20.0)
    parser.add_argument("--frame-push-url")
    args = parser.parse_args()

    raise SystemExit(
        run_pipeline(
            args.model,
            args.source,
            args.conf,
            args.iou,
            args.class_names,
            args.zones,
            args.smooth,
            args.log_dir,
            args.output,
            args.headless,
            args.max_frames,
            args.camera_id,
            args.inference_interval,
            args.alert_cooldown,
            args.live_frame,
            args.live_preview_fps,
            args.frame_push_url,
        )
    )
