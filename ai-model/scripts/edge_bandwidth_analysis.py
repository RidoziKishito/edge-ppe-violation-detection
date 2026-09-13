"""
Local bandwidth analysis for Trinity Edge deployment scenarios.

Run:
    python ai-model/scripts/edge_bandwidth_analysis.py
"""

from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AI_MODEL_DIR = SCRIPT_DIR.parent
REPO_ROOT = AI_MODEL_DIR.parent
EDGE_PIPELINE_DIR = REPO_ROOT / "edge-pipeline"

CONFIG = {
    "videos": [
        EDGE_PIPELINE_DIR / "demo_video3.mp4",
        EDGE_PIPELINE_DIR / "demo_video4.mp4",
    ],
    "output_dir": AI_MODEL_DIR / "outputs" / "edge_results",
    "summary_csv": AI_MODEL_DIR / "outputs" / "edge_results" / "bandwidth_summary.csv",
    "time_periods_seconds": {
        "1 hour": 60 * 60,
        "8 hours": 8 * 60 * 60,
        "30 days": 30 * 24 * 60 * 60,
    },
    "reference_stream_mbps": 2.0,
    "violation_events_per_minute": 1.0,
    "log_entry_bytes": 500,
    "snapshot_kb_min": 15,
    "snapshot_kb_max": 30,
    "critical_events_per_hour": 5.0,
    "blurred_frame_kb": 80,
}


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
    print(f"  pandas: {version_of('pandas')}")
    print(f"  onnxruntime: {version_of('onnxruntime')}")
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        gpu_note = "GPU provider available" if any("CUDA" in p for p in providers) else "CPU only"
        print(f"  ONNXRuntime providers: {providers} ({gpu_note})")
    except Exception as exc:
        print(f"  ONNXRuntime providers: unavailable ({exc})")
    print()


def require_dependencies():
    missing = []
    modules = {}
    for module_name in ["cv2", "pandas"]:
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

    return modules["cv2"], modules["pandas"]


def validate_inputs() -> None:
    missing = [path for path in CONFIG["videos"] if not path.exists()]
    if missing:
        print("ERROR: Required demo video file(s) not found.")
        for path in missing:
            print(f"  Expected: {path}")
        sys.exit(1)


def bytes_to_mb(num_bytes: float) -> float:
    return num_bytes / (1024 * 1024)


def kb_to_bytes(num_kb: float) -> float:
    return num_kb * 1024


def duration_seconds(video_path: Path, cv2_module) -> float:
    cap = cv2_module.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = cap.get(cv2_module.CAP_PROP_FPS) or 0.0
    frame_count = cap.get(cv2_module.CAP_PROP_FRAME_COUNT) or 0.0
    cap.release()
    if fps <= 0 or frame_count <= 0:
        raise RuntimeError(f"Could not determine duration for video: {video_path}")
    return frame_count / fps


def measure_videos(cv2_module) -> list[dict]:
    measurements = []
    for video_path in CONFIG["videos"]:
        size_bytes = video_path.stat().st_size
        duration_s = duration_seconds(video_path, cv2_module)
        mb_per_second = bytes_to_mb(size_bytes) / duration_s
        measurements.append(
            {
                "video": video_path.name,
                "size_mb": bytes_to_mb(size_bytes),
                "duration_s": duration_s,
                "mb_per_second": mb_per_second,
            }
        )
    return measurements


def weighted_demo_bitrate_mb_s(measurements: list[dict]) -> float:
    total_mb = sum(row["size_mb"] for row in measurements)
    total_seconds = sum(row["duration_s"] for row in measurements)
    if total_seconds <= 0:
        raise RuntimeError("Total demo video duration is zero.")
    return total_mb / total_seconds


def reference_stream_mb(seconds: float) -> float:
    bytes_per_second = CONFIG["reference_stream_mbps"] * 1_000_000 / 8
    return bytes_to_mb(bytes_per_second * seconds)


def edge_logs_snapshots_mb(seconds: float) -> float:
    events = seconds / 60.0 * CONFIG["violation_events_per_minute"]
    snapshot_avg_kb = (CONFIG["snapshot_kb_min"] + CONFIG["snapshot_kb_max"]) / 2.0
    bytes_per_event = CONFIG["log_entry_bytes"] + kb_to_bytes(snapshot_avg_kb)
    return bytes_to_mb(events * bytes_per_event)


def edge_critical_frames_mb(seconds: float) -> float:
    events = seconds / 3600.0 * CONFIG["critical_events_per_hour"]
    bytes_per_event = CONFIG["log_entry_bytes"] + kb_to_bytes(CONFIG["blurred_frame_kb"])
    return bytes_to_mb(events * bytes_per_event)


def reduction_pct(data_mb: float, baseline_mb: float) -> float:
    if baseline_mb <= 0:
        return 0.0
    return (1.0 - (data_mb / baseline_mb)) * 100.0


def build_rows(demo_bitrate_mb_s: float, measurements: list[dict]) -> list[dict]:
    rows = []
    video_note = "weighted from " + ", ".join(row["video"] for row in measurements)

    for period, seconds in CONFIG["time_periods_seconds"].items():
        scenario_a_mb = demo_bitrate_mb_s * seconds
        scenario_ref_mb = reference_stream_mb(seconds)
        scenario_b_mb = edge_logs_snapshots_mb(seconds)
        scenario_c_mb = edge_critical_frames_mb(seconds)

        rows.extend(
            [
                {
                    "scenario": "Scenario A - continuous demo-video streaming",
                    "time_period": period,
                    "data_mb": scenario_a_mb,
                    "bandwidth_reduction_pct": 0.0,
                    "notes": video_note,
                },
                {
                    "scenario": "Scenario A reference - continuous 1080p 2 Mbps streaming",
                    "time_period": period,
                    "data_mb": scenario_ref_mb,
                    "bandwidth_reduction_pct": reduction_pct(scenario_ref_mb, scenario_a_mb),
                    "notes": "reference bitrate only; not a reduction target",
                },
                {
                    "scenario": "Scenario B - edge logs + violation snapshots",
                    "time_period": period,
                    "data_mb": scenario_b_mb,
                    "bandwidth_reduction_pct": reduction_pct(scenario_b_mb, scenario_a_mb),
                    "notes": (
                        f"{CONFIG['violation_events_per_minute']} event/min, "
                        f"{CONFIG['log_entry_bytes']} B log, "
                        f"{CONFIG['snapshot_kb_min']}-{CONFIG['snapshot_kb_max']} KB snapshot"
                    ),
                },
                {
                    "scenario": "Scenario C - logs + blurred critical frames",
                    "time_period": period,
                    "data_mb": scenario_c_mb,
                    "bandwidth_reduction_pct": reduction_pct(scenario_c_mb, scenario_a_mb),
                    "notes": (
                        f"{CONFIG['critical_events_per_hour']} critical events/hour, "
                        f"{CONFIG['blurred_frame_kb']} KB blurred JPEG"
                    ),
                },
            ]
        )

    return rows


def print_video_measurements(measurements: list[dict]) -> None:
    print("Demo Video Measurements")
    print("video           | size_mb | duration_s | bitrate_mb_s")
    print("----------------+---------+------------+-------------")
    for row in measurements:
        print(
            f"{row['video']:<15} | "
            f"{row['size_mb']:>7.2f} | "
            f"{row['duration_s']:>10.2f} | "
            f"{row['mb_per_second']:>11.4f}"
        )
    print()


def print_table(rows: list[dict]) -> None:
    headers = ["scenario", "time_period", "data_mb", "bandwidth_reduction_pct", "notes"]
    display_rows = []
    for row in rows:
        display_rows.append(
            {
                "scenario": row["scenario"],
                "time_period": row["time_period"],
                "data_mb": f"{row['data_mb']:.2f}",
                "bandwidth_reduction_pct": f"{row['bandwidth_reduction_pct']:.2f}",
                "notes": row["notes"],
            }
        )

    widths = {
        header: max(len(header), *(len(str(row[header])) for row in display_rows))
        for header in headers
    }
    print("Bandwidth Summary")
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in display_rows:
        print(" | ".join(str(row[header]).ljust(widths[header]) for header in headers))
    print()


def main() -> int:
    print_environment()
    cv2_module, pd_module = require_dependencies()
    validate_inputs()
    CONFIG["output_dir"].mkdir(parents=True, exist_ok=True)

    measurements = measure_videos(cv2_module)
    demo_bitrate = weighted_demo_bitrate_mb_s(measurements)
    rows = build_rows(demo_bitrate, measurements)

    summary_df = pd_module.DataFrame(
        rows,
        columns=[
            "scenario",
            "time_period",
            "data_mb",
            "bandwidth_reduction_pct",
            "notes",
        ],
    )
    summary_df.to_csv(CONFIG["summary_csv"], index=False)

    print_video_measurements(measurements)
    print_table(rows)
    print(f"DONE - results saved to {CONFIG['summary_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
