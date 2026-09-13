# Trinity Dashboard
#
# Lightweight Flask dashboard for Trinity's construction-site PPE safety monitor.
# It reads edge log CSV/JSON files, normalizes alert events, and serves a
# Jinja2/vanilla JS interface suitable for edge-device demos.

from __future__ import annotations

import ast
import csv
import json
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, url_for


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
EDGE_PIPELINE_DIR = PROJECT_ROOT / "edge-pipeline"
EDGE_LOG_DIR = EDGE_PIPELINE_DIR / "logs"
RUNS_DIR = EDGE_LOG_DIR / "runs"
ACTIVE_RUN_PATH = EDGE_LOG_DIR / "active_run.json"
SAMPLE_EVENTS_PATH = BASE_DIR / "data" / "sample_events.json"

ZONE_NAMES = {
    "Z01": "Danger Zone (Lifting Area)",
    "Z02": "Warning Zone (Scaffolding)",
}

PPE_TYPES = ["no_helmet", "no_gloves", "no_boots", "no_goggle"]

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

LIVE_FRAME_CONDITION = threading.Condition(threading.Lock())
latest_live_frame: bytes | None = None
latest_live_frame_version = 0

active_zone_editor_process = None


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    candidates = [
        text.replace("Z", "+00:00"),
        text.replace(" ", "T"),
    ]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def serialize_timestamp(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return str(value or "")
    return parsed.replace(microsecond=0).isoformat()


def parse_list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip().lower() != "none"]
    text = str(value).strip()
    if not text or text.lower() == "none":
        return []
    if "|" in text:
        return [item.strip() for item in text.split("|") if item.strip()]
    if "," in text:
        return [item.strip() for item in text.split(",") if item.strip()]
    return [text]


def parse_box(value: Any) -> list[int] | None:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return [int(item) for item in value]
    try:
        parsed = ast.literal_eval(str(value))
    except (ValueError, SyntaxError):
        return None
    if isinstance(parsed, list) and len(parsed) == 4:
        return [int(item) for item in parsed]
    return None


def normalize_zone(value: Any) -> str:
    zones = parse_list_value(value)
    if not zones:
        return "Unassigned"
    return " | ".join(ZONE_NAMES.get(zone, zone) for zone in zones)


def normalize_event(raw: dict[str, Any], source: str) -> dict[str, Any] | None:
    timestamp = raw.get("timestamp")
    parsed_time = parse_timestamp(timestamp)
    if parsed_time is None:
        return None

    missing_ppe = raw.get("missing_ppe", raw.get("violation_type", []))
    frame_path = raw.get("frame_path", raw.get("snapshot_path"))
    box = raw.get("worker_id_box", raw.get("bbox"))

    return {
        "timestamp": serialize_timestamp(timestamp),
        "camera_id": str(raw.get("camera_id", "Unknown")),
        "zone": normalize_zone(raw.get("zone", raw.get("zone_id"))),
        "alert_level": str(raw.get("alert_level", "NORMAL")).upper(),
        "missing_ppe": parse_list_value(missing_ppe),
        "confidence": round(float(raw.get("confidence", 0.0) or 0.0), 3),
        "frame_path": None if not frame_path or str(frame_path).lower() == "none" else str(frame_path),
        "worker_id_box": parse_box(box),
        "source": source,
    }


def load_json_events(path: Path, source: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    records = raw if isinstance(raw, list) else raw.get("events", [])
    events = []
    for record in records:
        if isinstance(record, dict):
            event = normalize_event(record, source)
            if event:
                events.append(event)
    return events


def load_csv_events(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            event = normalize_event(row, path.name)
            if event:
                events.append(event)
    return events


def active_run() -> tuple[Path | None, dict[str, Any] | None]:
    try:
        pointer = json.loads(ACTIVE_RUN_PATH.read_text(encoding="utf-8"))
        run_dir = Path(pointer["run_dir"]).resolve()
        allowed_root = RUNS_DIR.resolve()
        if allowed_root not in run_dir.parents or not run_dir.is_dir():
            return None, None
        metadata_path = run_dir / "run.json"
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else pointer
        )
        return run_dir, metadata
    except (FileNotFoundError, KeyError, json.JSONDecodeError, OSError):
        return None, None


def load_run_events(run_dir: Path) -> list[dict[str, Any]]:
    events = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name != "run.json":
            events.extend(load_json_events(path, path.name))
    for path in sorted(run_dir.glob("*.csv")):
        events.extend(load_csv_events(path))
    return events


def load_events() -> list[dict[str, Any]]:
    run_dir, _ = active_run()
    if run_dir:
        return sorted(
            load_run_events(run_dir),
            key=lambda item: item["timestamp"],
            reverse=True,
        )

    events = load_json_events(SAMPLE_EVENTS_PATH, "sample_events.json")
    if EDGE_LOG_DIR.exists():
        for path in sorted(EDGE_LOG_DIR.glob("*.json")):
            events.extend(load_json_events(path, path.name))
        for path in sorted(EDGE_LOG_DIR.glob("*.csv")):
            events.extend(load_csv_events(path))
    return sorted(events, key=lambda item: item["timestamp"], reverse=True)


def resolve_snapshot_path(frame_path: str | None) -> Path | None:
    if not frame_path:
        return None
    
    # Normalize all backslashes to forward slashes before any path resolution
    normalized = frame_path.replace("\\", "/")
    raw = Path(normalized)
    
    if raw.is_absolute():
        candidate = raw
    else:
        if normalized.startswith("edge-pipeline/"):
            candidate = PROJECT_ROOT / normalized
        elif normalized.startswith("logs/"):
            # Maps logs/snapshots/<filename> to EDGE_LOG_DIR / "snapshots" / <filename>
            # we strip the "logs/" prefix (length 5) so it becomes snapshots/<filename>
            candidate = EDGE_LOG_DIR / normalized[5:]
        else:
            candidate = EDGE_LOG_DIR / normalized

    try:
        resolved = candidate.resolve()
        allowed_root = EDGE_LOG_DIR.resolve()
        if allowed_root == resolved or allowed_root in resolved.parents:
            return resolved if resolved.is_file() else None
    except OSError:
        return None
    return None


def snapshot_url(frame_path: str | None) -> str | None:
    if resolve_snapshot_path(frame_path) is None:
        return None
    return url_for("api_snapshot", path=frame_path)


def event_with_snapshot_url(event: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(event)
    enriched["snapshot_url"] = snapshot_url(event.get("frame_path"))
    return enriched


def active_live_frame() -> Path | None:
    run_dir, _ = active_run()
    if not run_dir:
        return None
    live_frame = run_dir / "live_frame.jpg"
    return live_frame if live_frame.is_file() else None


def update_live_frame(frame_bytes: bytes) -> int:
    global latest_live_frame, latest_live_frame_version
    with LIVE_FRAME_CONDITION:
        latest_live_frame = bytes(frame_bytes)
        latest_live_frame_version += 1
        LIVE_FRAME_CONDITION.notify_all()
        return latest_live_frame_version


def mjpeg_frames():
    last_version = 0
    while True:
        with LIVE_FRAME_CONDITION:
            LIVE_FRAME_CONDITION.wait_for(
                lambda: (
                    latest_live_frame is not None
                    and latest_live_frame_version != last_version
                ),
                timeout=5.0,
            )
            frame = latest_live_frame
            last_version = latest_live_frame_version

        if frame is None:
            time.sleep(0.1)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
            + frame
            + b"\r\n"
        )


@app.route("/")
def index():
    return render_template("index.html", active_page="monitor")


@app.route("/analytics")
def analytics():
    return render_template("analytics.html", active_page="analytics", ppe_types=PPE_TYPES)


@app.route("/events")
def events_page():
    return render_template("events.html", active_page="events", ppe_types=PPE_TYPES)


@app.route("/status")
def status():
    nodes = [
        {"camera_id": "CAM-01", "location": "Main Entrance", "status": "online", "fps": 31, "heartbeat": "4s ago"},
        {"camera_id": "CAM-02", "location": "Floor 3 East", "status": "online", "fps": 29, "heartbeat": "7s ago"},
        {"camera_id": "CAM-03", "location": "Ground Level", "status": "online", "fps": 30, "heartbeat": "5s ago"},
        {"camera_id": "CAM-04", "location": "Crane Zone", "status": "offline", "fps": 0, "heartbeat": "12m ago"},
    ]
    return render_template("status.html", active_page="status", nodes=nodes)


@app.route("/api/events")
def api_events():
    events = [event_with_snapshot_url(event) for event in load_events()]
    limit = request.args.get("limit", type=int)
    if limit is not None and limit > 0:
        events = events[:limit]
    return jsonify({"events": events, "count": len(events)})


@app.route("/api/stats")
def api_stats():
    events = load_events()
    today = date.today()
    todays_events = [
        event for event in events if (parse_timestamp(event["timestamp"]) or datetime.min).date() == today
    ]
    latest_frame_url = None
    for event in events:
        latest_frame_url = snapshot_url(event.get("frame_path"))
        if latest_frame_url:
            break
    return jsonify(
        {
            "total_alerts_today": len(todays_events),
            "warning_today": sum(1 for event in todays_events if event["alert_level"] == "WARNING"),
            "critical_today": sum(1 for event in todays_events if event["alert_level"] == "CRITICAL"),
            "latest_frame_url": latest_frame_url,
            "live_frame_url": (
                url_for("api_live_frame") if active_live_frame() else None
            ),
            "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        }
    )


@app.route("/api/run")
def api_run():
    run_dir, metadata = active_run()
    return jsonify(
        {
            "active": run_dir is not None,
            "run": metadata,
        }
    )


@app.route("/api/live-frame")
def api_live_frame():
    live_frame = active_live_frame()
    if live_frame is None:
        abort(404)
    response = send_file(
        live_frame,
        mimetype="image/jpeg",
        conditional=False,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/push-frame", methods=["POST"])
def api_push_frame():
    frame = request.get_data(cache=False)
    if not frame:
        abort(400)
    if len(frame) > 5 * 1024 * 1024:
        abort(413)
    if not frame.startswith(b"\xff\xd8"):
        abort(400)

    version = update_live_frame(frame)
    return jsonify({"ok": True, "version": version})


@app.route("/api/edit-zones", methods=["POST"])
def api_edit_zones():
    global active_zone_editor_process
    
    if active_zone_editor_process is not None and active_zone_editor_process.poll() is None:
        return jsonify({"ok": False, "error": "Editor is already open"}), 400

    run_dir, metadata = active_run()
    if not run_dir or not metadata:
        return jsonify({"ok": False, "error": "No active run"}), 400
    
    source_name = metadata.get("source")
    if not source_name:
        return jsonify({"ok": False, "error": "Source not found in metadata"}), 400

    import subprocess
    import sys
    
    check_py_path = EDGE_PIPELINE_DIR / "check.py"
    source_path = EDGE_PIPELINE_DIR / "media" / "videos" / "input" / source_name
    if not source_path.exists():
        source_path = EDGE_PIPELINE_DIR / source_name
        if not source_path.exists():
             source_path = PROJECT_ROOT / source_name
             
    # Run the zone editor without showing a console window
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    active_zone_editor_process = subprocess.Popen([
        sys.executable,
        str(check_py_path),
        "--source",
        str(source_path)
    ], cwd=str(EDGE_PIPELINE_DIR), creationflags=creation_flags)
    
    return jsonify({"ok": True, "message": "Zone editor launched"})


@app.route("/video-feed")
def video_feed():
    response = Response(
        mjpeg_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/snapshot")
def api_snapshot():
    path = request.args.get("path")
    resolved = resolve_snapshot_path(path)
    if resolved is None:
        abort(404)
    return send_file(resolved)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
