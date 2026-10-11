"""Local video selection and supervised pipeline runs for the dashboard."""
from __future__ import annotations

import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from uuid import uuid4

import cv2
from werkzeug.utils import secure_filename


VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def source_key(path):
    resolved = Path(path).resolve()
    parts = resolved.as_posix().casefold()
    # Keep library identities stable when the repository is moved to another machine.
    for marker in ("/media/videos/input/", "/media/videos/uploads/"):
        if marker in parts:
            parts = marker + parts.split(marker, 1)[1]
            break
    return hashlib.sha256(parts.encode()).hexdigest()[:20]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class VideoWorkflow:
    def __init__(self, project_root, active_run):
        self.root = Path(project_root)
        self.edge = self.root / "edge-pipeline"
        self.runs = self.edge / "logs" / "runs"
        self.pointer = self.edge / "logs" / "active_run.json"
        self.zones = self.edge / "configs" / "zones"
        self.uploads = self.edge / "media" / "videos" / "uploads"
        self.input_dir = self.edge / "media" / "videos" / "input"
        configured = Path(os.environ.get("TRINITY_CMOT_DIR", str(self.input_dir / "CMOT")))
        self.cmot = configured if configured.is_absolute() else self.root / configured
        project_v1 = Path(os.environ.get("TRINITY_PROJECTV1_DIR", str(self.input_dir / "Projectv1")))
        self.project_v1 = project_v1 if project_v1.is_absolute() else self.root / project_v1
        self.get_active = active_run
        self.lock = threading.RLock()
        self.process = None
        self.stop_requested = False

    def catalog(self):
        entries = []
        roots = [(self.cmot / split, split) for split in ("train", "valid", "val", "validation", "test")]
        roots += [(self.project_v1, "projectv1"), (self.input_dir, "local"), (self.uploads, "uploaded")]
        seen = set()
        for folder, split in roots:
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                    if path.resolve() in seen:
                        continue
                    seen.add(path.resolve())
                    entries.append({"id": source_key(path), "name": path.name, "camera_id": path.stem,
                                    "split": "valid" if split in {"val", "validation"} else split, "path": path.resolve()})
        return entries

    def busy(self):
        _, metadata = self.get_active()
        return self.process is not None or (metadata or {}).get("status") in {"starting", "running", "stopping"}

    def model_path(self, metadata):
        candidates = [Path(metadata["model"])] if metadata and metadata.get("model") else []
        configured = os.environ.get("TRINITY_MODEL")
        if configured:
            model = Path(configured)
            candidates.insert(0, model if model.is_absolute() else self.root / model)
        candidates += [self.root / "models" / "baseline_yolo26n_best.onnx", self.edge / "baseline_yolo26n_best.onnx", self.root.parent / "Models" / "baseline_yolo26n_best.onnx", self.edge / "best.onnx"]
        return next((path.resolve() for path in candidates if path.is_file()), None)

    def person_model_path(self, metadata):
        candidates = []
        if metadata and metadata.get("person_model"):
            candidates.append(Path(metadata["person_model"]))
        configured = os.environ.get("TRINITY_PERSON_MODEL")
        if configured:
            model = Path(configured)
            candidates.insert(0, model if model.is_absolute() else self.root / model)
        candidates += [
            self.root / "models" / "yolo11n.onnx",
            self.edge / "yolo11n.onnx",
            self.root.parent / "Models" / "yolo11n.onnx",
            self.root.parent / "Models" / "yolo11n.pt",
        ]
        return next((path.resolve() for path in candidates if path.is_file()), None)

    def prepare(self, path):
        """Validate the video before replacing the active run pointer."""
        with self.lock:
            if self.busy():
                raise ValueError("Stop the current run before selecting another video.")
            capture = cv2.VideoCapture(str(path))
            try:
                ok, frame = capture.read()
            finally:
                capture.release()
            if not ok:
                raise ValueError("This file could not be decoded as a video. Try an MP4 with H.264 video.")
            height, width = frame.shape[:2]
            _, previous = self.get_active()
            model = self.model_path(previous)
            person_model = self.person_model_path(previous)
            confidence = float((previous or {}).get("confidence", 0.4))
            key = source_key(path)
            run_id = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{secure_filename(path.stem)}"
            run_dir = self.runs / run_id
            run_dir.mkdir(parents=True)
            zone_path = self.zones / f"input_{key}.json"
            # Each selected source has its own working profile. Never overwrite legacy profiles.
            if not zone_path.exists():
                write_json(zone_path, {"source": path.name, "width": width, "height": height, "zones": []})
            metadata = {"run_id": run_id, "status": "ready", "source": str(path), "source_name": path.name,
                        "source_key": key, "camera_id": path.stem, "model": str(model) if model else "",
                        "ppe_model": str(model) if model else "",
                        "person_model": str(person_model) if person_model else "",
                        "zone_profile": str(zone_path), "width": width, "height": height,
                        "headless": True, "confidence": confidence, "person_confidence": 0.2,
                        "iou": 0.45, "smoothing_frames": 5,
                        "inference_interval": 3, "alert_cooldown_seconds": 5, "live_preview_fps": 12,
                        "prepared_at": datetime.now().isoformat(timespec="seconds")}
            cv2.imwrite(str(run_dir / "live_frame.jpg"), frame)
            write_json(run_dir / "run.json", metadata)
            write_json(self.pointer, {"run_id": run_id, "run_dir": str(run_dir)})
            return metadata

    def update_settings(self, confidence):
        """Persist lightweight inference settings for the next run."""
        with self.lock:
            if self.busy():
                raise ValueError("Stop the active detection run before changing PPE confidence.")
            run_dir, metadata = self.get_active()
            if run_dir is None or metadata is None:
                raise ValueError("Select an input video before changing PPE confidence.")
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                raise ValueError("PPE confidence must be a number.") from None
            if not 0.1 <= confidence <= 0.9:
                raise ValueError("PPE confidence must be between 0.10 and 0.90.")
            metadata["confidence"] = round(confidence, 2)
            write_json(run_dir / "run.json", metadata)
            return metadata

    def select(self, identifier):
        entry = next((entry for entry in self.catalog() if entry["id"] == identifier), None)
        if not entry:
            raise ValueError("Video not found in the local library.")
        return self.prepare(entry["path"])

    def upload(self, upload):
        with self.lock:
            if self.busy():
                raise ValueError("Stop the current run before uploading another video.")
            name = secure_filename(upload.filename or "")
            if not name or Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
                raise ValueError("Choose an MP4, AVI, MOV, MKV, WEBM or M4V video.")
            folder = self.uploads / uuid4().hex
            folder.mkdir(parents=True)
            path = folder / name
            try:
                upload.save(path)
                return self.prepare(path)
            except Exception:
                path.unlink(missing_ok=True)
                folder.rmdir()
                raise

    def start(self, dashboard_url):
        with self.lock:
            if self.busy():
                raise ValueError("A pipeline is already running.")
            run_dir, metadata = self.get_active()
            if not metadata or not Path(metadata.get("source", "")).is_file():
                raise ValueError("Select an input video first.")
            model = self.model_path(metadata)
            if model is None:
                raise ValueError("No ONNX model found. Add baseline_yolo26n_best.onnx to the Models folder.")
            person_model = self.person_model_path(metadata)
            installed = importlib.metadata.version("ultralytics")
            if tuple(int(part) for part in installed.split(".")[:3]) < (8, 4, 56):
                raise ValueError(f"Ultralytics {installed} cannot safely run this YOLO26 setup. "
                                 "Use python dashboard/run_local.py or install edge-pipeline/requirements.txt in your environment.")
            for dependency in ("onnx", "onnxruntime", "lap"):
                if importlib.util.find_spec(dependency) is None:
                    raise ValueError(f"Missing {dependency}. Install the pipeline requirements before starting detection.")
            if metadata.get("status") != "ready":
                source = Path(metadata["source"])
                old_profile = Path(metadata["zone_profile"])
                old_data = json.loads(old_profile.read_text(encoding="utf-8"))
                asset_id = metadata.get("zone_asset_id")
                self.prepare(source)
                run_dir, metadata = self.get_active()
                write_json(Path(metadata["zone_profile"]), old_data)
                metadata["zone_asset_id"] = asset_id
            metadata.update(status="starting", model=str(model), ppe_model=str(model),
                            person_model=str(person_model) if person_model else "",
                            detector_mode="dual" if person_model else "single",
                            started_at=datetime.now().isoformat(timespec="seconds"),
                            frame_push_url=f"{dashboard_url}/api/push-frame")
            write_json(run_dir / "zones_snapshot.json", json.loads(Path(metadata["zone_profile"]).read_text(encoding="utf-8")))
            metadata["ultralytics_version"] = installed
            metadata["python_version"] = sys.version.split()[0]
            command = [sys.executable, "-u", "edge_infer.py", "--model", str(model),
                       "--source", metadata["source"],
                       "--zones", metadata["zone_profile"], "--headless", "--camera-id", metadata["camera_id"],
                       "--run-id", metadata["run_id"],
                       "--conf", str(metadata["confidence"]), "--iou", str(metadata["iou"]),
                       "--smooth", str(metadata["smoothing_frames"]), "--inference-interval", str(metadata["inference_interval"]),
                       "--alert-cooldown", str(metadata["alert_cooldown_seconds"]), "--log-dir", str(run_dir),
                       "--output", str(run_dir / "output.mp4"), "--live-frame", str(run_dir / "live_frame.jpg"),
                       "--debug-output", str(run_dir / "output_debug.mp4"),
                       "--debug-live-frame", str(run_dir / "live_frame_debug.jpg"),
                       "--live-preview-fps", str(metadata["live_preview_fps"]), "--frame-push-url", metadata["frame_push_url"]]
            if person_model:
                command += ["--person-model", str(person_model),
                            "--person-conf", str(metadata.get("person_confidence", 0.2))]
            log = (run_dir / "pipeline.log").open("ab")
            environment = os.environ.copy()
            environment["YOLO_AUTOINSTALL"] = "false"
            import onnxruntime
            if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
                environment["CUDA_VISIBLE_DEVICES"] = "-1"
            try:
                self.process = subprocess.Popen(command, cwd=self.edge, stdout=log, stderr=subprocess.STDOUT, env=environment,
                                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            except Exception:
                log.close()
                raise
            self.stop_requested = False
            write_json(run_dir / "run.json", metadata)
            threading.Thread(target=self._watch, args=(self.process, run_dir, log), daemon=True).start()
            return metadata

    @staticmethod
    def _make_browser_playable(path):
        """Replace an OpenCV MP4 with an H.264 fast-start MP4 when ffmpeg is available."""
        if not path.is_file() or not path.stat().st_size:
            return False
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError, OSError):
            return False
        temporary = path.with_name(f".{path.stem}.browser.mp4")
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ],
                check=False,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode != 0 or not temporary.is_file() or not temporary.stat().st_size:
                return False
            temporary.replace(path)
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def _prune_older_source_runs(self, source_identity, keep_dir):
        """Keep only the latest run archive for one selected input video."""
        if not source_identity or not self.runs.is_dir():
            return
        keep_dir = keep_dir.resolve()
        for folder in self.runs.iterdir():
            try:
                resolved = folder.resolve()
                if resolved == keep_dir or resolved.parent != self.runs.resolve():
                    continue
                metadata_path = resolved / "run.json"
                if not metadata_path.is_file():
                    continue
                previous = json.loads(metadata_path.read_text(encoding="utf-8"))
                if previous.get("source_key") == source_identity:
                    shutil.rmtree(resolved)
            except (OSError, ValueError, json.JSONDecodeError):
                continue

    def _watch(self, process, run_dir, log):
        try:
            code = process.wait()
            browser_video_ready = False
            debug_video_ready = False
            if code == 0:
                with self.lock:
                    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                    metadata["status"] = "finalizing"
                    write_json(run_dir / "run.json", metadata)
                browser_video_ready = self._make_browser_playable(run_dir / "output.mp4")
                debug_video_ready = self._make_browser_playable(run_dir / "output_debug.mp4")
            with self.lock:
                metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                metadata.update(status="stopped" if self.stop_requested else "completed" if code == 0 else "error",
                                return_code=code, finished_at=datetime.now().isoformat(timespec="seconds"),
                                browser_video_ready=browser_video_ready,
                                debug_video_ready=debug_video_ready)
                if code != 0 and not self.stop_requested:
                    lines = (run_dir / "pipeline.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    metadata["error_message"] = lines[-1][:500] if lines else f"Pipeline exited with code {code}."
                write_json(run_dir / "run.json", metadata)
                if code == 0:
                    self._prune_older_source_runs(metadata.get("source_key"), run_dir)
        finally:
            log.close()
            with self.lock:
                self.process = None

    def stop(self):
        with self.lock:
            if self.process is None:
                raise ValueError("No dashboard-managed run to stop. Runs started from a terminal must be stopped there.")
            self.stop_requested = True
            run_dir, metadata = self.get_active()
            (run_dir / "stop.request").touch()
            metadata["status"] = "stopping"
            write_json(run_dir / "run.json", metadata)
            process = self.process
            def force_stop_if_stuck():
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.terminate()
            threading.Thread(target=force_stop_if_stuck, daemon=True).start()
            return {"ok": True, "message": "Stopping the current run."}
