# Trinity Dashboard
#
# Lightweight Flask dashboard for Trinity's construction-site PPE safety monitor.
# It reads edge log CSV/JSON files, normalizes alert events, and serves a
# Jinja2/vanilla JS interface suitable for edge-device demos.

from __future__ import annotations

import ast
import csv
import json
import shutil
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
import hashlib
import re

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, url_for


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
EDGE_PIPELINE_DIR = PROJECT_ROOT / "edge-pipeline"
EDGE_LOG_DIR = EDGE_PIPELINE_DIR / "logs"
RUNS_DIR = EDGE_LOG_DIR / "runs"
ACTIVE_RUN_PATH = EDGE_LOG_DIR / "active_run.json"
SAMPLE_EVENTS_PATH = BASE_DIR / "data" / "sample_events.json"
ZONES_DIR = EDGE_PIPELINE_DIR / "configs" / "zones"
ASSETS_DIR = BASE_DIR / "data" / "zone_assets"

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
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

try:
    from .workflow import VideoWorkflow, source_key, write_json
except ImportError:
    from workflow import VideoWorkflow, source_key, write_json

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
        "zone_ids": parse_list_value(raw.get("zone", raw.get("zone_id"))),
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
        if path.name not in {"run.json", "progress.json", "zones_snapshot.json"}:
            events.extend(load_json_events(path, path.name))
    for path in sorted(run_dir.glob("*.csv")):
        events.extend(load_csv_events(path))
    try:
        metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        profile_path = run_dir / "zones_snapshot.json"
        if not profile_path.is_file():
            profile_path = active_zone_path(metadata)
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path and profile_path.is_file() else {}
    except (OSError, ValueError):
        profile = {}
    zone_map = {zone["id"]: zone for zone in profile.get("zones", []) if isinstance(zone, dict) and "id" in zone}
    for event in events:
        event["run_id"] = run_dir.name
        ids = event.get("zone_ids", [])
        event["zone_types"] = sorted({zone_map[item]["type"] if item in zone_map else
                                      "danger_zone" if item == "Z01" or "danger" in item.lower() else
                                      "warning_zone" if item == "Z02" or "warning" in item.lower() else "unassigned" for item in ids})
        if ids:
            event["zone"] = " | ".join(zone_map.get(item, {}).get("name", ZONE_NAMES.get(item, item)) for item in ids)
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


def active_source_path(metadata: dict[str, Any] | None) -> Path | None:
    """Resolve the input belonging to the active run without accepting user paths."""
    if not metadata:
        return None

    candidates: list[Path] = []
    source = metadata.get("source")
    if source:
        candidates.append(Path(str(source)).expanduser())

    source_name = metadata.get("source_name")
    if source_name:
        candidates.extend(
            [
                EDGE_PIPELINE_DIR / "media" / "videos" / "input" / str(source_name),
                EDGE_PIPELINE_DIR / str(source_name),
                PROJECT_ROOT / str(source_name),
            ]
        )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def active_zone_path(metadata: dict[str, Any] | None) -> Path | None:
    """Return only zone profiles stored in the project's zone directory."""
    if not metadata:
        return None

    configured = metadata.get("zone_profile")
    source = metadata.get("source_name") or metadata.get("source")
    candidate = (
        Path(str(configured)).expanduser()
        if configured
        else ZONES_DIR / f"{Path(str(source)).stem}.json" if source else None
    )
    if candidate is None:
        return None

    try:
        resolved = candidate.resolve()
        allowed_root = ZONES_DIR.resolve()
    except OSError:
        return None
    if allowed_root != resolved.parent:
        return None
    return resolved


def load_zone_profile() -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None]:
    _, metadata = active_run()
    zone_path = active_zone_path(metadata)
    if zone_path is None:
        return None, None, metadata

    source_path = active_source_path(metadata)
    default_profile: dict[str, Any] = {
        "source": source_path.name if source_path else metadata.get("source_name") if metadata else None,
        "width": 0,
        "height": 0,
        "zones": [],
    }
    try:
        profile = json.loads(zone_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        profile = default_profile
    if not isinstance(profile, dict):
        profile = default_profile
    profile.setdefault("zones", [])
    return zone_path, profile, metadata


def validate_zone_payload(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "Expected a JSON object"

    try:
        width = int(payload.get("width", 0))
        height = int(payload.get("height", 0))
    except (TypeError, ValueError):
        return None, "Frame width and height must be integers"
    if width <= 0 or height <= 0:
        return None, "Frame dimensions are unavailable"

    raw_zones = payload.get("zones")
    if not isinstance(raw_zones, list):
        return None, "Zones must be a list"
    if len(raw_zones) > 50:
        return None, "A profile can contain at most 50 zones"

    zones: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    allowed_types = {"danger_zone", "warning_zone"}
    for index, raw_zone in enumerate(raw_zones, start=1):
        if not isinstance(raw_zone, dict):
            return None, f"Zone {index} is invalid"
        zone_id = str(raw_zone.get("id", "")).strip()
        name = str(raw_zone.get("name", "")).strip()
        zone_type = str(raw_zone.get("type", "")).strip()
        polygon = raw_zone.get("polygon")
        if not zone_id or len(zone_id) > 32:
            return None, f"Zone {index} needs a valid ID"
        if zone_id in seen_ids:
            return None, f"Duplicate zone ID: {zone_id}"
        if not name or len(name) > 80:
            return None, f"Zone {zone_id} needs a valid name"
        if zone_type not in allowed_types:
            return None, f"Zone {zone_id} has an unsupported type"
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 100:
            return None, f"Zone {zone_id} needs between 3 and 100 points"

        points: list[list[int]] = []
        for point in polygon:
            if not isinstance(point, list) or len(point) != 2:
                return None, f"Zone {zone_id} contains an invalid point"
            try:
                x, y = int(round(float(point[0]))), int(round(float(point[1])))
            except (TypeError, ValueError):
                return None, f"Zone {zone_id} contains a non-numeric point"
            if not 0 <= x <= width or not 0 <= y <= height:
                return None, f"Zone {zone_id} contains a point outside the frame"
            points.append([x, y])

        seen_ids.add(zone_id)
        zones.append({"id": zone_id, "name": name, "type": zone_type, "polygon": points})

    return {"width": width, "height": height, "zones": zones}, None


def update_live_frame(frame_bytes: bytes) -> int:
    global latest_live_frame, latest_live_frame_version
    with LIVE_FRAME_CONDITION:
        latest_live_frame = bytes(frame_bytes)
        latest_live_frame_version += 1
        LIVE_FRAME_CONDITION.notify_all()
        return latest_live_frame_version


def mjpeg_frames():
    last_version = 0
    last_disk_stamp = None
    while True:
        with LIVE_FRAME_CONDITION:
            LIVE_FRAME_CONDITION.wait_for(
                lambda: (
                    latest_live_frame is not None
                    and latest_live_frame_version != last_version
                ),
                timeout=0.25,
            )
            frame = latest_live_frame if latest_live_frame_version != last_version else None
            last_version = latest_live_frame_version

        # A failed push must not freeze the preview: the pipeline also writes an atomic JPEG.
        disk = active_live_frame()
        if disk is not None:
            try:
                stamp = (str(disk), disk.stat().st_mtime_ns)
                if frame is None and stamp != last_disk_stamp:
                    frame = disk.read_bytes()
                last_disk_stamp = stamp
            except OSError:
                pass

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


@app.route("/zones")
def zones_page():
    return render_template("zones.html", active_page="monitor", monitor_tab="zones")


@app.route("/status")
def status():
    return render_template("status.html", active_page="status")


@app.route("/api/events")
def api_events():
    if request.args.get("run_id"):
        run_dir = archived_run_path(request.args["run_id"])
        events = [event_with_snapshot_url(event) for event in load_run_events(run_dir)]
        events.sort(key=lambda event: event["timestamp"], reverse=True)
    elif request.args.get("scope") == "all":
        records = []
        for run_dir in sorted(RUNS_DIR.glob("*")):
            if run_dir.is_dir():
                records.extend(load_run_events(run_dir))
        events = [event_with_snapshot_url(event) for event in sorted(records, key=lambda event: event["timestamp"], reverse=True)]
    else:
        events = [event_with_snapshot_url(event) for event in load_events()]
    limit = request.args.get("limit", type=int)
    if limit is not None and limit > 0:
        events = events[:limit]
    return jsonify({"events": events, "count": len(events)})


RUN_FILES = {"video": "output.mp4", "events": "events.csv", "log": "pipeline.log",
             "metadata": "run.json", "progress": "progress.json", "zones": "zones_snapshot.json"}


def archived_run_path(run_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        abort(404)
    folder = (RUNS_DIR / run_id).resolve()
    if folder.parent != RUNS_DIR.resolve() or not (folder / "run.json").is_file():
        abort(404)
    return folder


def archived_run_summary(folder):
    metadata = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    progress = {}
    try:
        progress = json.loads((folder / "progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    files = {}
    for kind, name in RUN_FILES.items():
        path = folder / name
        if path.is_file() and path.resolve().parent == folder.resolve():
            if kind == "video" and (metadata.get("status") not in {"completed", "stopped"} or metadata.get("return_code", 0) != 0 or not path.stat().st_size):
                continue
            files[kind] = {"name": name, "bytes": path.stat().st_size,
                           "url": url_for("api_run_file", run_id=folder.name, kind=kind)}
    return {"id": folder.name, "source_name": metadata.get("source_name", "Unknown"),
            "status": metadata.get("status", "unknown"), "started_at": metadata.get("started_at"),
            "finished_at": metadata.get("finished_at"), "model": Path(metadata.get("model", "")).name,
            "frames": progress.get("frame"), "event_count": len(load_run_events(folder)),
            "folder": str(folder), "files": files}


@app.route("/api/runs")
def api_runs():
    runs = []
    for folder in sorted(RUNS_DIR.glob("*"), reverse=True):
        if not folder.is_dir() or folder.resolve().parent != RUNS_DIR.resolve():
            continue
        try:
            item = archived_run_summary(folder)
            if item["started_at"]:
                runs.append(item)
        except (OSError, ValueError, TypeError):
            continue
    return jsonify(runs=runs)


@app.route("/api/runs/<run_id>")
def api_run_archive(run_id):
    folder = archived_run_path(run_id)
    item = archived_run_summary(folder)
    log = folder / "pipeline.log"
    item["log_tail"] = "No runtime log saved."
    if log.is_file() and log.resolve().parent == folder:
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - 65536))
            item["log_tail"] = handle.read().decode("utf-8", errors="replace")
    return jsonify(run=item)


@app.route("/api/runs/<run_id>/files/<kind>")
def api_run_file(run_id, kind):
    folder = archived_run_path(run_id)
    if kind not in RUN_FILES:
        abort(404)
    item = archived_run_summary(folder)
    if kind not in item["files"]:
        abort(404)
    path = folder / RUN_FILES[kind]
    return send_file(path, as_attachment=True, download_name=f"{run_id}_{path.name}", conditional=True)


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
    if run_dir and metadata:
        try:
            progress = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
            metadata["progress"] = progress
            if metadata.get("status") == "starting" and progress.get("stage") == "running":
                metadata["status"] = "running"
        except (OSError, ValueError):
            pass
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


@app.route("/api/zones", methods=["GET", "POST"])
def api_zones():
    zone_path, profile, metadata = load_zone_profile()
    if zone_path is None or profile is None or metadata is None:
        return jsonify({"ok": False, "error": "No active run or zone profile is available"}), 404

    if request.method == "GET":
        width = int(profile.get("width") or 0)
        height = int(profile.get("height") or 0)
        source_path = active_source_path(metadata)
        if (width <= 0 or height <= 0) and source_path is not None:
            try:
                import cv2

                capture = cv2.VideoCapture(str(source_path))
                try:
                    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                finally:
                    capture.release()
            except (ImportError, OSError):
                pass
        profile["width"] = width
        profile["height"] = height
        return jsonify(
            {
                "ok": True,
                "profile": profile,
                "profile_name": zone_path.name,
                "source_name": metadata.get("source_name") or (source_path.name if source_path else "Unknown"),
                "frame_url": url_for("api_zone_frame"),
            }
        )

    payload = request.get_json(silent=True)
    clean, error = validate_zone_payload(payload)
    if error or clean is None:
        return jsonify({"ok": False, "error": error}), 400

    source_path = active_source_path(metadata)
    clean["source"] = source_path.name if source_path else metadata.get("source_name")
    zone_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = zone_path.with_suffix(zone_path.suffix + ".bak")
    temporary_path = zone_path.with_suffix(zone_path.suffix + ".tmp")
    try:
        if zone_path.is_file():
            shutil.copy2(zone_path, backup_path)
        temporary_path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        temporary_path.replace(zone_path)
        if payload.get("save_asset"):
            asset = save_zone_asset(clean, metadata, payload.get("asset_name"))
            run_dir, latest_metadata = active_run()
            latest_metadata["zone_asset_id"] = asset["id"]
            latest_metadata["zone_preview"] = True
            write_json(run_dir / "run.json", latest_metadata)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        return jsonify({"ok": False, "error": f"Could not save zone profile: {exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "message": "Zone profile saved",
            "profile": clean,
            "profile_name": zone_path.name,
        }
    )


workflow = VideoWorkflow(PROJECT_ROOT, active_run)


def save_zone_asset(profile, metadata, name):
    source = active_source_path(metadata)
    key = source_key(source) if source else metadata.get("source_key")
    name = str(name or f"{metadata.get('source_name', 'Video')} zones").strip()[:80]
    identifier = hashlib.sha256(f"{key}:{name}".encode()).hexdigest()[:24]
    asset = {"id": identifier, "name": name, "source_key": key,
             "source_name": metadata.get("source_name"), "profile": profile,
             "updated_at": datetime.now().isoformat(timespec="seconds")}
    write_json(ASSETS_DIR / f"{identifier}.json", asset)
    return asset


@app.route("/api/videos", methods=["GET", "POST"])
def api_videos():
    if request.method == "GET":
        return jsonify(videos=[{key: value for key, value in entry.items() if key != "path"} for entry in workflow.catalog()])
    try:
        if "video" in request.files:
            metadata = workflow.upload(request.files["video"])
        else:
            metadata = workflow.select((request.get_json(silent=True) or {}).get("id"))
        with LIVE_FRAME_CONDITION:
            global latest_live_frame
            latest_live_frame = None
        return jsonify(ok=True, run=metadata)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    except OSError:
        return jsonify(ok=False, error="Could not store the input video. Check available disk space."), 500


@app.route("/api/run/start", methods=["POST"])
def api_start_run():
    try:
        with LIVE_FRAME_CONDITION:
            global latest_live_frame
            latest_live_frame = None
        port = int(request.environ.get("SERVER_PORT", 5000))
        return jsonify(ok=True, run=workflow.start(f"http://127.0.0.1:{port}"))
    except (ValueError, OSError) as error:
        return jsonify(ok=False, error=str(error)), 400


@app.route("/api/run/stop", methods=["POST"])
def api_stop_run():
    try:
        return jsonify(workflow.stop())
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400


@app.route("/api/zone-assets", methods=["GET"])
def api_zone_assets():
    _, metadata = active_run()
    source = active_source_path(metadata)
    key = source_key(source) if source else None
    assets = []
    for path in sorted(ASSETS_DIR.glob("*.json")):
        try:
            asset = json.loads(path.read_text(encoding="utf-8"))
            if key and asset.get("source_key") == key:
                assets.append({field: asset.get(field) for field in ("id", "name", "source_name", "updated_at")})
        except (OSError, ValueError):
            continue
    return jsonify(assets=assets, active_id=(metadata or {}).get("zone_asset_id"), source_name=(metadata or {}).get("source_name"))


@app.route("/api/zone-assets/apply", methods=["POST"])
def api_apply_zone_asset():
    identifier = str((request.get_json(silent=True) or {}).get("id", ""))
    if len(identifier) != 24 or any(char not in "0123456789abcdef" for char in identifier):
        return jsonify(ok=False, error="Invalid asset ID."), 400
    with workflow.lock:
        run_dir, metadata = active_run()
        source = active_source_path(metadata)
        zone_path = active_zone_path(metadata)
        if source is None or zone_path is None:
            return jsonify(ok=False, error="Select an input video first."), 400
        try:
            asset = json.loads((ASSETS_DIR / f"{identifier}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return jsonify(ok=False, error="Asset not found."), 404
        if asset.get("source_key") != source_key(source):
            return jsonify(ok=False, error="This asset belongs to a different video."), 400
        profile, error = validate_zone_payload(asset.get("profile"))
        if error:
            return jsonify(ok=False, error=error), 400
        profile["source"] = source.name
        if zone_path.is_file():
            shutil.copy2(zone_path, zone_path.with_suffix(".json.bak"))
        write_json(zone_path, profile)
        metadata.update(zone_asset_id=identifier, zone_preview=True)
        write_json(run_dir / "run.json", metadata)
        return jsonify(ok=True, profile=profile, asset_name=asset["name"])


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify(ok=False, error="This video exceeds the 2 GB upload limit. Select it from the local CMOT library instead."), 413


@app.route("/api/zone-frame")
def api_zone_frame():
    run_dir, metadata = active_run()
    source_path = active_source_path(metadata)
    if source_path is not None:
        if source_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return send_file(source_path, max_age=0)
        try:
            import cv2

            capture = cv2.VideoCapture(str(source_path))
            try:
                ok, frame = capture.read()
            finally:
                capture.release()
            if ok:
                encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if encoded:
                    response = Response(buffer.tobytes(), mimetype="image/jpeg")
                    response.headers["Cache-Control"] = "no-store"
                    return response
        except (ImportError, OSError):
            pass

    fallback = active_live_frame()
    if fallback is None and run_dir is not None:
        candidate = run_dir / "live_frame.jpg"
        fallback = candidate if candidate.is_file() else None
    if fallback is None:
        abort(404)
    response = send_file(fallback, mimetype="image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/edit-zones", methods=["POST"])
def api_edit_zones():
    global active_zone_editor_process
    
    if active_zone_editor_process is not None and active_zone_editor_process.poll() is None:
        return jsonify({"ok": False, "error": "Editor is already open"}), 400

    run_dir, metadata = active_run()
    if not run_dir or not metadata:
        return jsonify({"ok": False, "error": "No active run"}), 400
    
    source_path = active_source_path(metadata)
    if source_path is None:
        return jsonify({"ok": False, "error": "Source not found in metadata"}), 400

    import subprocess
    import sys
    
    check_py_path = EDGE_PIPELINE_DIR / "check.py"
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
