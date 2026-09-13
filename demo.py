import argparse
import json
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parent
EDGE_DIR = PROJECT_ROOT / "edge-pipeline"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
DEMO_VIDEO_DIR = EDGE_DIR / "media" / "videos" / "input"
LOG_DIR = EDGE_DIR / "logs"
RUNS_DIR = LOG_DIR / "runs"
ACTIVE_RUN_PATH = LOG_DIR / "active_run.json"
DEFAULT_MODEL = EDGE_DIR / "baseline_yolo26n_best.onnx"
DASHBOARD_URL = "http://127.0.0.1:5000"


def resolve_edge_path(value):
    path = Path(value).expanduser()
    if path.is_file():
        return path.resolve()
    demo_video_path = DEMO_VIDEO_DIR / path
    if demo_video_path.is_file():
        return demo_video_path.resolve()
    edge_path = EDGE_DIR / path
    if edge_path.is_file():
        return edge_path.resolve()
    return path.resolve()


def port_is_open(host="127.0.0.1", port=5000):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_dashboard(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_is_open():
            return True
        time.sleep(0.25)
    return False


def start_dashboard():
    if port_is_open():
        print("Dashboard is already running.")
        return None

    print("Starting dashboard...")
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=DASHBOARD_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    if not wait_for_dashboard():
        process.terminate()
        raise RuntimeError(
            "Dashboard did not start. Install dashboard requirements with "
            "'python -m pip install -r dashboard/requirements.txt'."
        )
    return process


def zone_profile_matches(profile_path, source):
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    profile_source = profile.get("source")
    if profile_source and profile_source != source.name:
        return False

    profile_width = profile.get("width")
    profile_height = profile.get("height")
    if not profile_width or not profile_height:
        return False

    cap = cv2.VideoCapture(str(source))
    try:
        if not cap.isOpened():
            return False
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    return int(profile_width) == width and int(profile_height) == height


def configure_zones(source, profile_path):
    print(f"Configuring zones for {source.name}...")
    result = subprocess.run(
        [
            sys.executable,
            "check.py",
            "--source",
            str(source),
            "--output",
            str(profile_path),
        ],
        cwd=EDGE_DIR,
        check=False,
    )
    if result.returncode != 0 or not profile_path.is_file():
        raise RuntimeError("Zone configuration was cancelled or did not save.")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_run(source, model, zone_profile, args):
    run_id = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{source.stem}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    metadata = {
        "run_id": run_id,
        "status": "starting",
        "source": str(source),
        "source_name": source.name,
        "model": str(model),
        "zone_profile": str(zone_profile),
        "camera_id": args.camera_id or source.stem,
        "started_at": datetime.now().replace(microsecond=0).isoformat(),
        "headless": args.headless,
        "max_frames": args.max_frames,
        "confidence": args.conf,
        "iou": args.iou,
        "smoothing_frames": args.smooth,
        "inference_interval": args.inference_interval,
        "alert_cooldown_seconds": args.alert_cooldown,
        "live_preview_fps": args.live_preview_fps,
        "frame_push_url": (
            f"{DASHBOARD_URL}/api/push-frame"
            if not getattr(args, "no_dashboard", False)
            else None
        ),
    }
    write_json(run_dir / "run.json", metadata)
    write_json(
        ACTIVE_RUN_PATH,
        {"run_id": run_id, "run_dir": str(run_dir), "updated_at": metadata["started_at"]},
    )
    return run_dir, metadata


def run_pipeline(source, model, zone_profile, run_dir, args):
    command = [
        sys.executable,
        "edge_infer.py",
        "--model",
        str(model),
        "--source",
        str(source),
        "--zones",
        str(zone_profile),
        "--conf",
        str(args.conf),
        "--iou",
        str(args.iou),
        "--smooth",
        str(args.smooth),
        "--log-dir",
        str(run_dir),
        "--output",
        str(run_dir / "output.mp4"),
        "--camera-id",
        args.camera_id or source.stem,
        "--inference-interval",
        str(args.inference_interval),
        "--alert-cooldown",
        str(args.alert_cooldown),
        "--live-frame",
        str(run_dir / "live_frame.jpg"),
        "--live-preview-fps",
        str(args.live_preview_fps),
    ]
    if not getattr(args, "no_dashboard", False):
        command.extend(["--frame-push-url", f"{DASHBOARD_URL}/api/push-frame"])
        # If using dashboard, hide the OpenCV window by default to avoid confusion
        if not getattr(args, "show_window", False) and "--headless" not in command:
            command.append("--headless")
    elif args.headless:
        command.append("--headless")
        
    if args.max_frames:
        command.extend(["--max-frames", str(args.max_frames)])
    return subprocess.run(command, cwd=EDGE_DIR, check=False).returncode


def main():
    parser = argparse.ArgumentParser(
        description="Launch a complete Trinity pipeline and dashboard demo."
    )
    parser.add_argument("--source", required=True, help="Video path or filename")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--camera-id")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--smooth", type=int, default=5)
    parser.add_argument("--inference-interval", type=int, default=3)
    parser.add_argument("--alert-cooldown", type=float, default=5.0)
    parser.add_argument("--live-preview-fps", type=float, default=20.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--configure-zones", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    source = resolve_edge_path(args.source)
    model = resolve_edge_path(args.model)
    if not source.is_file():
        parser.error(f"Video does not exist: {source}")
    if not model.is_file():
        parser.error(f"Model does not exist: {model}")

    zone_profile = EDGE_DIR / "configs" / "zones" / f"{source.stem}.json"
    if args.configure_zones or not zone_profile_matches(zone_profile, source):
        if args.headless:
            parser.error(
                f"Zone profile is missing for {source.name}. Run once without "
                "--headless or use --configure-zones."
            )
        configure_zones(source, zone_profile)
    else:
        print(f"Using zone profile: {zone_profile}")

    run_dir, metadata = create_run(source, model, zone_profile, args)
    print(f"Active run: {metadata['run_id']}")

    if not args.no_dashboard:
        start_dashboard()
        if not args.no_browser:
            webbrowser.open(DASHBOARD_URL)
        print(f"Dashboard: {DASHBOARD_URL}")

    metadata["status"] = "running"
    write_json(run_dir / "run.json", metadata)
    return_code = run_pipeline(source, model, zone_profile, run_dir, args)
    metadata["status"] = "completed" if return_code == 0 else "failed"
    metadata["finished_at"] = datetime.now().replace(microsecond=0).isoformat()
    metadata["return_code"] = return_code
    write_json(run_dir / "run.json", metadata)

    print(f"Run status: {metadata['status']}")
    print(f"Run files: {run_dir}")
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
