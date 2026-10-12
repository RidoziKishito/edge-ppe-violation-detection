import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
from ultralytics import YOLO


def prepare_onnx_runtime():
    """Let ONNX Runtime reuse CUDA/cuDNN DLLs from the matching Torch build."""
    try:
        import onnxruntime as ort

        preload_dlls = getattr(ort, "preload_dlls", None)
        if preload_dlls is not None:
            preload_dlls()
    except (ImportError, OSError) as exc:
        print(f"ONNX Runtime CUDA preload skipped: {exc}", flush=True)


prepare_onnx_runtime()

import display
import rule_engine
from logger import EdgeLogger
from person_tracker import DEFAULT_TRACK_LOW_THRESH, PersonTracker
from pipeline_control import (
    WorkerEventEngine,
    should_publish_live_frame,
    should_run_inference,
)
import worker_state


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


def _class_ids(model, class_name):
    names = model.names
    items = names.items() if isinstance(names, dict) else enumerate(names)
    return [int(class_id) for class_id, name in items if str(name).lower() == class_name.lower()]


def infer_person_detections(
    model,
    frame,
    conf_thres,
    iou_thres,
    track_low_thresh=DEFAULT_TRACK_LOW_THRESH,
):
    """Detect people with a general-purpose detector for ByteTrack input."""
    persons = []
    person_class_ids = _class_ids(model, "person")
    if not person_class_ids:
        raise ValueError("The person detector does not expose a 'person' class.")
    results = model(
        frame,
        stream=True,
        verbose=False,
        # Keep weak Person boxes available for ByteTrack's second association.
        # They can rescue an existing ID, but cannot create a new track because
        # new tracks still have to pass new_track_thresh in PersonTracker.
        conf=min(float(conf_thres), float(track_low_thresh)),
        iou=iou_thres,
        classes=person_class_ids,
    )
    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = float(box.conf[0])
            persons.append({
                "box": (x1, y1, x2, y2),
                "conf": confidence,
                "class_name": "Person",
            })
    return persons


def infer_ppe_detections(model, frame, conf_thres, iou_thres):
    """Detect PPE evidence while deliberately ignoring this model's Person class."""
    detections = []
    results = model(
        frame,
        stream=True,
        verbose=False,
        conf=conf_thres,
        iou=iou_thres,
    )
    for result in results:
        for box in result.boxes:
            class_name = model.names[int(box.cls[0])]
            if str(class_name).lower() == "person":
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = math.ceil(float(box.conf[0]) * 100) / 100
            detections.append({
                "box": (x1, y1, x2, y2),
                "conf": confidence,
                "class_name": class_name,
            })
    return detections


def infer_detections(model, frame, conf_thres, iou_thres):
    """Backward-compatible single-detector inference used by older callers."""
    persons = []
    other_detections = []
    results = model(
        frame,
        stream=True,
        verbose=False,
        conf=min(float(conf_thres), DEFAULT_TRACK_LOW_THRESH),
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
            if str(class_name).lower() == "person":
                persons.append(detection)
            elif confidence >= conf_thres:
                other_detections.append(detection)
    return persons, other_detections


def render_worker_view(frame, zones_config, states):
    """Render the operator view: one worker box and one PPE summary card."""
    display.draw_zones(frame, zones_config)
    for state in states:
        violations = worker_state.state_violations(state)
        alert_level = rule_engine.classify_alert(state["active_zones"], violations)
        display.draw_worker_card(frame, state, alert_level)
    return frame


def render_debug_view(frame, zones_config, persons, ppe_detections):
    """Render every raw Person and PPE detection for model inspection."""
    display.draw_zones(frame, zones_config)
    display.draw_debug_detections(frame, persons, ppe_detections)
    return frame


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
    run_id=None,
    person_model_path=None,
    person_conf_thres=0.2,
    debug_output_path=None,
    debug_live_frame_path=None,
):
    del classes_path  # Kept for CLI compatibility.
    progress_path = Path(log_dir) / "progress.json"
    stop_path = Path(log_dir) / "stop.request"
    progress = {"stage": "loading", "message": "Loading detector and video…", "frame": 0}

    def report(**updates):
        progress.update(updates, updated_at=time.time())
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = progress_path.with_name(
            f".{progress_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        try:
            temporary.write_text(json.dumps(progress), encoding="utf-8")
            for attempt in range(5):
                try:
                    os.replace(temporary, progress_path)
                    break
                except PermissionError:
                    if attempt == 4:
                        print(
                            f"Warning: progress file is temporarily locked: {progress_path}",
                            flush=True,
                        )
                        break
                    time.sleep(0.02 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)

    report()
    ppe_model = YOLO(model_path, task="detect")
    person_model = (
        YOLO(person_model_path, task="detect") if person_model_path else ppe_model
    )
    detector_mode = "dual" if person_model_path else "single"
    print(
        f"Detector mode={detector_mode}; PPE model={model_path}; "
        f"Person model={person_model_path or model_path}",
        flush=True,
    )
    zones_config = load_zones(zones_path)

    video_source = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"Error: Could not open video source: {source}")
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    report(total_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), source_fps=fps)
    validate_zone_profile(zones_config, width, height)

    out_path = output_path or str(Path(str(source)).with_suffix("")) + "_output.mp4"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        out_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    debug_out_path = debug_output_path or str(
        Path(out_path).with_name(f"{Path(out_path).stem}_debug{Path(out_path).suffix}")
    )
    Path(debug_out_path).parent.mkdir(parents=True, exist_ok=True)
    debug_writer = cv2.VideoWriter(
        debug_out_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    window_name = "Trinity Edge - Safety Pipeline"
    if not headless:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    source_name = os.path.splitext(os.path.basename(str(source)))[0]
    resolved_camera_id = camera_id or source_name
    resolved_run_id = run_id or (
        Path(log_dir).name if Path(log_dir).name != "logs" else f"run_{source_name}"
    )
    safety_logger = EdgeLogger(
        log_dir=log_dir,
        source_name=source_name,
        filename="events.csv" if Path(log_dir).name != "logs" else None,
        run_id=resolved_run_id,
    )
    event_engine = WorkerEventEngine(
        required_frames=smooth_frames,
        cooldown_seconds=alert_cooldown,
    )
    tracker = PersonTracker()
    cached_worker_states = []
    cached_unassigned_evidence = []
    cached_person_detections = []
    cached_ppe_detections = []
    cached_lost_track_ids = set()
    cached_removed_track_ids = set()
    cached_ppe_detection_count = 0
    last_live_frame_at = None
    frame_push_failures = 0
    frame_id = 0
    started_processing = None
    last_report_at = 0

    last_zones_mtime = 0
    if Path(zones_path).exists():
        last_zones_mtime = Path(zones_path).stat().st_mtime

    print(
        "Running video stream. "
        f"Smoothing={smooth_frames}, inference interval={inference_interval}, "
        f"alert cooldown={alert_cooldown}s. Press 'q' or 'X' to exit."
    )

    while True:
        if stop_path.exists():
            break
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
            if started_processing is None:
                report(stage="warming", message="Preparing inference backend and first detection. Please wait…")
            if person_model_path:
                persons = infer_person_detections(
                    person_model, frame, person_conf_thres, iou_thres
                )
                other_detections = infer_ppe_detections(
                    ppe_model, frame, conf_thres, iou_thres
                )
            else:
                persons, other_detections = infer_detections(
                    ppe_model, frame, conf_thres, iou_thres
                )
            cached_ppe_detection_count = len(other_detections)
            cached_person_detections = persons
            cached_ppe_detections = other_detections
            tracking = tracker.update(persons, frame)
            cached_lost_track_ids = tracking.lost_track_ids
            cached_removed_track_ids = tracking.removed_track_ids
            timestamp_ms = int(((frame_id - 1) / fps) * 1000)
            cached_worker_states, cached_unassigned_evidence = (
                worker_state.build_worker_states(
                    tracking.active,
                    other_detections,
                    zones_config,
                    resolved_camera_id,
                    resolved_run_id,
                    frame_id,
                    timestamp_ms,
                )
            )
            if started_processing is None:
                started_processing = time.monotonic()
                print("First detection complete. Publishing live frames.", flush=True)

        worker_frame = render_worker_view(
            frame.copy(), zones_config, cached_worker_states
        )
        debug_frame = render_debug_view(
            frame.copy(),
            zones_config,
            cached_person_detections,
            cached_ppe_detections,
        )
        observations = worker_state.worker_observations(cached_worker_states)

        if inference_frame:
            video_time_seconds = (frame_id - 1) / fps
            valid_logs = event_engine.process(
                observations,
                video_time_seconds,
                active_track_ids={
                    state["track_id"] for state in cached_worker_states
                },
                lost_track_ids=cached_lost_track_ids,
                removed_track_ids=cached_removed_track_ids,
                worker_ppe_states={
                    (state["track_id"], ppe_type): record["state"]
                    for state in cached_worker_states
                    for ppe_type, record in state["ppe"].items()
                },
                frame_id=frame_id,
            )
            for log_data in valid_logs:
                safety_logger.log_event(log_data, frame_img=worker_frame)

        video_time_seconds = (frame_id - 1) / fps
        if (live_frame_path or frame_push_url) and should_publish_live_frame(
            video_time_seconds,
            last_live_frame_at,
            live_preview_fps,
        ):
            frame_bytes = encode_live_frame(worker_frame)
            debug_frame_bytes = encode_live_frame(debug_frame)
            if frame_bytes is not None:
                if live_frame_path:
                    write_live_frame(frame_bytes, live_frame_path)
                if frame_push_url and frame_push_failures < 3:
                    if push_live_frame(frame_bytes, frame_push_url):
                        frame_push_failures = 0
                    else:
                        frame_push_failures += 1
                last_live_frame_at = video_time_seconds
            if debug_frame_bytes is not None and debug_live_frame_path:
                write_live_frame(debug_frame_bytes, debug_live_frame_path)

        writer.write(worker_frame)
        debug_writer.write(debug_frame)
        now = time.monotonic()
        if now - last_report_at >= 0.5:
            report(stage="running", message="Detection running", frame=frame_id,
                   persons=len(cached_worker_states), ppe_detections=cached_ppe_detection_count,
                   video_seconds=(frame_id - 1) / fps,
                   processing_fps=round(max(0, frame_id - 1) / max(0.001, now - started_processing), 1))
            last_report_at = now
        if not headless:
            cv2.imshow(window_name, worker_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_AUTOSIZE) == -1:
                    break
            except cv2.error:
                break

    final_video_time = (max(1, frame_id) - 1) / fps
    for log_data in event_engine.close_all(final_video_time, frame_id):
        safety_logger.log_event(log_data)
    cap.release()
    writer.release()
    debug_writer.release()
    report(stage="stopped" if stop_path.exists() else "completed", frame=frame_id,
           message="Stopped" if stop_path.exists() else "Video completed")
    if not headless:
        cv2.destroyAllWindows()
    print(f"Output video saved to: {out_path}")
    print(f"Debug video saved to: {debug_out_path}")
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
    parser.add_argument("--run-id")
    parser.add_argument("--person-model")
    parser.add_argument("--person-conf", type=float, default=0.2)
    parser.add_argument("--debug-output")
    parser.add_argument("--debug-live-frame")
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
            args.run_id,
            args.person_model,
            args.person_conf,
            args.debug_output,
            args.debug_live_frame,
        )
    )
