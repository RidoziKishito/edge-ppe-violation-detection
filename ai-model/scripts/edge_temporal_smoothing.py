"""
Local temporal smoothing analysis for Trinity Edge alert stability.

Run:
    python ai-model/scripts/edge_temporal_smoothing.py
"""

from __future__ import annotations

import importlib
import json
import math
import platform
import sys
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AI_MODEL_DIR = SCRIPT_DIR.parent
REPO_ROOT = AI_MODEL_DIR.parent
EDGE_PIPELINE_DIR = REPO_ROOT / "edge-pipeline"

CONFIG = {
    "model_candidates": [
        AI_MODEL_DIR
        / "outputs"
        / "baseline_yolo26n"
        / "ppe_experiment_package"
        / "exports"
        / "baseline_yolo26n_best.onnx",
        AI_MODEL_DIR / "outputs" / "baseline_yolo26n" / "weights" / "best.onnx",
        AI_MODEL_DIR / "best.onnx",
    ],
    "videos": [
        EDGE_PIPELINE_DIR / "demo_video3.mp4",
        EDGE_PIPELINE_DIR / "demo_video4.mp4",
    ],
    "zones_path": EDGE_PIPELINE_DIR / "configs" / "zones.json",
    "output_dir": AI_MODEL_DIR / "outputs" / "edge_results",
    "summary_csv": AI_MODEL_DIR
    / "outputs"
    / "edge_results"
    / "event_vs_frame_metrics.csv",
    "conf_threshold": 0.4,
    "iou_threshold": 0.45,
    "smoothing_frames": [3, 5, 10],
}


ALERT_PRIORITY = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


def version_of(module_name: str) -> str:
    try:
        module = importlib.import_module(module_name)
        return str(getattr(module, "__version__", "installed"))
    except Exception:
        return "not installed"


def print_environment() -> None:
    print("Environment")
    print(f"  Python: {platform.python_version()} ({sys.executable})")
    print(f"  Platform: {platform.platform()}")
    print(f"  opencv-python: {version_of('cv2')}")
    print(f"  numpy: {version_of('numpy')}")
    print(f"  pandas: {version_of('pandas')}")
    print(f"  ultralytics: {version_of('ultralytics')}")

    try:
        import torch
        print(f"  torch CUDA available: {torch.cuda.is_available()}")
    except Exception as exc:
        print(f"  torch CUDA available: unknown ({exc})")

    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        gpu_note = "GPU provider available" if any("CUDA" in p for p in providers) else "CPU only"
        print(f"  onnxruntime: {ort.__version__}")
        print(f"  ONNXRuntime providers: {providers} ({gpu_note})")
    except Exception as exc:
        print(f"  onnxruntime: unavailable")
        print(f"  ONNXRuntime providers: unavailable ({exc})")

    print()


def require_dependencies():
    missing = []
    modules = {}
    for module_name in ["cv2", "pandas", "ultralytics"]:
        try:
            modules[module_name] = importlib.import_module(module_name)
        except Exception:
            missing.append(module_name)

    if missing:
        print("ERROR: Missing required dependencies:")
        for name in missing:
            package_name = "opencv-python" if name == "cv2" else name
            print(f"  - {package_name}")
        print("Install the edge dependencies and rerun this script.")
        sys.exit(1)

    if str(EDGE_PIPELINE_DIR) not in sys.path:
        sys.path.insert(0, str(EDGE_PIPELINE_DIR))

    try:
        rule_engine = importlib.import_module("rule_engine")
    except Exception as exc:
        print(f"ERROR: Could not import rule_engine from {EDGE_PIPELINE_DIR}: {exc}")
        sys.exit(1)

    return modules["cv2"], modules["pandas"], modules["ultralytics"].YOLO, rule_engine


def find_model_path() -> Path:
    for path in CONFIG["model_candidates"]:
        if path.exists():
            return path

    print("ERROR: baseline_yolo26n ONNX model not found.")
    print("Expected one of:")
    for path in CONFIG["model_candidates"]:
        print(f"  - {path}")
    sys.exit(1)


def validate_inputs() -> None:
    missing = []
    for video in CONFIG["videos"]:
        if not video.exists():
            missing.append(video)
    if not CONFIG["zones_path"].exists():
        missing.append(CONFIG["zones_path"])

    if missing:
        print("ERROR: Required input file(s) not found.")
        for path in missing:
            print(f"  Expected: {path}")
        sys.exit(1)


def load_zones() -> dict:
    with open(CONFIG["zones_path"], "r", encoding="utf-8") as f:
        return json.load(f)


def highest_alert(levels) -> str:
    if not levels:
        return "NORMAL"
    return max(levels, key=lambda level: ALERT_PRIORITY.get(level, 0))


def update_zone_alert(current_alerts: dict, zone_key: str, alert_level: str) -> None:
    existing_level = current_alerts.get(zone_key, "NORMAL")
    if ALERT_PRIORITY[alert_level] > ALERT_PRIORITY.get(existing_level, 0):
        current_alerts[zone_key] = alert_level


def detections_from_results(results, model) -> tuple[list[dict], list[dict]]:
    persons = []
    other_detections = []

    for result in results:
        names = getattr(result, "names", None) or getattr(model, "names", {})
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = math.ceil(float(box.conf[0]) * 100) / 100
            cls_idx = int(box.cls[0])
            cls_name = names.get(cls_idx, str(cls_idx)) if isinstance(names, dict) else str(cls_idx)
            det_obj = {
                "box": (x1, y1, x2, y2),
                "conf": conf,
                "class_name": cls_name,
            }
            if cls_name.lower() == "person":
                persons.append(det_obj)
            else:
                other_detections.append(det_obj)

    return persons, other_detections


def frame_alerts_from_detections(persons, other_detections, zones_config, rule_engine) -> dict:
    current_alerts = {}

    for person in persons:
        x1, _y1, x2, y2 = person["box"]
        center_point = ((x1 + x2) // 2, y2)
        active_zones = rule_engine.get_person_zones(center_point, zones_config)
        ppe_violations = rule_engine.check_ppe_violation(person["box"], other_detections)
        alert_level = rule_engine.classify_alert(active_zones, ppe_violations)

        if alert_level != "NORMAL":
            zone_key = "|".join([z["id"] for z in active_zones]) if active_zones else "NO_ZONE"
            update_zone_alert(current_alerts, zone_key, alert_level)

    violation_classes = {
        "no_helmet",
        "no_goggle",
        "no_gloves",
        "no_boots",
        "none",
    }

    for det in other_detections:
        vx_center = (det["box"][0] + det["box"][2]) // 2
        vy_center = (det["box"][1] + det["box"][3]) // 2
        inside_person = False

        for person in persons:
            px1, py1, px2, py2 = person["box"]
            if px1 <= vx_center <= px2 and py1 <= vy_center <= py2:
                inside_person = True
                break

        if inside_person:
            continue

        center_point = (vx_center, det["box"][3])
        active_zones = rule_engine.get_person_zones(center_point, zones_config)
        cls_name_lower = det["class_name"].lower()
        ppe_violations = [det["class_name"]] if cls_name_lower in violation_classes else []
        alert_level = rule_engine.classify_alert(active_zones, ppe_violations)

        if alert_level != "NORMAL":
            zone_key = "|".join([z["id"] for z in active_zones]) if active_zones else "NO_ZONE"
            update_zone_alert(current_alerts, zone_key, alert_level)

    return current_alerts


def count_smoothed_events(zone_alerts_by_frame: list[dict], required_frames: int) -> Counter:
    states = {}
    event_counts = Counter()

    for current_alerts in zone_alerts_by_frame:
        active_zone_keys = set(current_alerts.keys())
        tracked_zone_keys = set(states.keys()).union(active_zone_keys)

        for zone_key in tracked_zone_keys:
            current_level = current_alerts.get(zone_key, "NORMAL")
            state = states.setdefault(
                zone_key,
                {"level": "NORMAL", "count": 0, "confirmed_level": "NORMAL"},
            )

            if current_level == state["level"]:
                state["count"] += 1
            else:
                state["level"] = current_level
                state["count"] = 1
                state["confirmed_level"] = "NORMAL"

            if current_level in {"WARNING", "CRITICAL"} and state["count"] == required_frames:
                event_counts[current_level] += 1
                state["confirmed_level"] = current_level

    return event_counts


def process_video(video_path: Path, model, zones_config, rule_engine, cv2_module) -> dict:
    cap = cv2_module.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    frame_counts = Counter()
    zone_alerts_by_frame = []
    total_frames = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        total_frames += 1
        results = model.predict(
            frame,
            verbose=False,
            conf=CONFIG["conf_threshold"],
            iou=CONFIG["iou_threshold"],
            device="cuda:0",
        )
        persons, other_detections = detections_from_results(results, model)
        zone_alerts = frame_alerts_from_detections(
            persons,
            other_detections,
            zones_config,
            rule_engine,
        )
        frame_level = highest_alert(zone_alerts.values())
        frame_counts[frame_level] += 1
        zone_alerts_by_frame.append(zone_alerts)

    cap.release()
    return {
        "total_frames": total_frames,
        "frame_counts": frame_counts,
        "zone_alerts_by_frame": zone_alerts_by_frame,
    }


def build_rows(video_path: Path, metrics: dict) -> list[dict]:
    total_frames = metrics["total_frames"]
    frame_counts = metrics["frame_counts"]
    frame_alert_count = frame_counts["WARNING"] + frame_counts["CRITICAL"]
    rows = [
        {
            "video": video_path.name,
            "level": "FRAME_LEVEL",
            "N_frames": 0,
            "total_frames": total_frames,
            "warning_count": frame_counts["WARNING"],
            "critical_count": frame_counts["CRITICAL"],
            "alert_rate": (frame_alert_count / total_frames) if total_frames else 0.0,
            "fp_reduction_pct": 0.0,
        }
    ]

    for n_frames in CONFIG["smoothing_frames"]:
        event_counts = count_smoothed_events(metrics["zone_alerts_by_frame"], n_frames)
        event_count = event_counts["WARNING"] + event_counts["CRITICAL"]
        if frame_alert_count > 0:
            reduction = max(0.0, (1.0 - (event_count / frame_alert_count)) * 100.0)
        else:
            reduction = 0.0
        rows.append(
            {
                "video": video_path.name,
                "level": "EVENT_LEVEL",
                "N_frames": n_frames,
                "total_frames": total_frames,
                "warning_count": event_counts["WARNING"],
                "critical_count": event_counts["CRITICAL"],
                "alert_rate": (event_count / total_frames) if total_frames else 0.0,
                "fp_reduction_pct": reduction,
            }
        )

    return rows


def print_table(rows: list[dict]) -> None:
    headers = [
        "video",
        "level",
        "N_frames",
        "total_frames",
        "warning_count",
        "critical_count",
        "alert_rate",
        "fp_reduction_pct",
    ]
    display_rows = []
    for row in rows:
        display_rows.append(
            {
                "video": row["video"],
                "level": row["level"],
                "N_frames": row["N_frames"],
                "total_frames": row["total_frames"],
                "warning_count": row["warning_count"],
                "critical_count": row["critical_count"],
                "alert_rate": f"{row['alert_rate']:.4f}",
                "fp_reduction_pct": f"{row['fp_reduction_pct']:.2f}",
            }
        )

    widths = {
        header: max(len(header), *(len(str(row[header])) for row in display_rows))
        for header in headers
    }
    print("Pseudo-stability Metrics (No Ground Truth)")
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in display_rows:
        print(" | ".join(str(row[header]).ljust(widths[header]) for header in headers))
    print()


def print_frame_counts(video_metrics: list[tuple[Path, dict]]) -> None:
    print("Frame-Level Alert Counts")
    print("video           | normal_count | warning_count | critical_count | total_frames")
    print("----------------+--------------+---------------+----------------+-------------")
    for video_path, metrics in video_metrics:
        counts = metrics["frame_counts"]
        total_frames = metrics["total_frames"]
        print(
            f"{video_path.name:<15} | "
            f"{counts['NORMAL']:>12} | "
            f"{counts['WARNING']:>13} | "
            f"{counts['CRITICAL']:>14} | "
            f"{total_frames:>11}"
        )
    print()


def main() -> int:
    print_environment()
    cv2_module, pd_module, YOLO, rule_engine = require_dependencies()
    validate_inputs()
    model_path = find_model_path()
    zones_config = load_zones()
    CONFIG["output_dir"].mkdir(parents=True, exist_ok=True)

    print("Pseudo-stability metrics only: no ground-truth annotations are used.")
    print(f"Selected model: {model_path}")
    print(f"Zones: {CONFIG['zones_path']}")
    print()

    model = YOLO(str(model_path))
    all_rows = []
    video_metrics = []
    for video_path in CONFIG["videos"]:
        print(f"Processing {video_path.name}")
        metrics = process_video(video_path, model, zones_config, rule_engine, cv2_module)
        video_metrics.append((video_path, metrics))
        all_rows.extend(build_rows(video_path, metrics))

    summary_df = pd_module.DataFrame(
        all_rows,
        columns=[
            "video",
            "level",
            "N_frames",
            "total_frames",
            "warning_count",
            "critical_count",
            "alert_rate",
            "fp_reduction_pct",
        ],
    )
    summary_df.to_csv(CONFIG["summary_csv"], index=False)

    print()
    print_frame_counts(video_metrics)
    print_table(all_rows)
    print(f"DONE - results saved to {CONFIG['summary_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
