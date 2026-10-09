import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from dashboard.workflow import VideoWorkflow, source_key, write_json


class DashboardWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = importlib.import_module("dashboard.app")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflow = VideoWorkflow(self.root, self.dashboard.active_run)
        self.workflow.cmot = self.root / "cmot"
        self.source = self.workflow.cmot / "train" / "0003.avi"
        self.source.parent.mkdir(parents=True)
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*"MJPG"), 5, (64, 48))
        for _ in range(3):
            writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
        writer.release()
        self.patches = [patch.object(self.dashboard, name, value) for name, value in {
            "RUNS_DIR": self.workflow.runs, "ACTIVE_RUN_PATH": self.workflow.pointer,
            "ZONES_DIR": self.workflow.zones, "ASSETS_DIR": self.root / "assets", "workflow": self.workflow,
        }.items()]
        for item in self.patches:
            item.start()
        self.client = self.dashboard.app.test_client()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def select(self):
        entries = self.client.get("/api/videos").get_json()["videos"]
        response = self.client.post("/api/videos", json={"id": entries[0]["id"]})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["run"]

    def test_catalog_and_selection_create_ready_preview(self):
        videos = self.client.get("/api/videos").get_json()["videos"]
        self.assertEqual(videos[0]["camera_id"], "0003")
        self.assertEqual(videos[0]["split"], "train")
        self.assertNotIn("path", videos[0])
        run = self.select()
        self.assertEqual(run["status"], "ready")
        self.assertEqual(run["width"], 64)
        response = self.client.get("/api/live-frame")
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.post("/api/videos", json={"id": "../../secret"}).status_code, 400)

    def test_library_id_is_portable_and_cmot_is_not_duplicated(self):
        first = self.root / "machine-a" / "media" / "videos" / "input" / "CMOT" / "test" / "0003.mp4"
        second = self.root / "machine-b" / "media" / "videos" / "input" / "CMOT" / "test" / "0003.mp4"
        self.assertEqual(source_key(first), source_key(second))
        self.workflow.cmot = self.workflow.input_dir / "CMOT"
        destination = self.workflow.cmot / "valid" / "0003.avi"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(self.source.read_bytes())
        entries = self.workflow.catalog()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["split"], "valid")

    def test_asset_save_apply_and_source_isolation(self):
        run = self.select()
        profile = self.client.get("/api/zones").get_json()["profile"]
        profile["zones"] = [{"id": "Z99", "name": "Crane area", "type": "danger_zone", "polygon": [[1, 1], [30, 1], [30, 30]]}]
        response = self.client.post("/api/zones", json={**profile, "save_asset": True, "asset_name": "Site A"})
        self.assertEqual(response.status_code, 200)
        assets = self.client.get("/api/zone-assets").get_json()["assets"]
        self.assertEqual(len(assets), 1)
        asset_id = assets[0]["id"]
        write_json(Path(run["zone_profile"]), {**profile, "zones": []})
        applied = self.client.post("/api/zone-assets/apply", json={"id": asset_id})
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.get_json()["profile"]["zones"][0]["id"], "Z99")
        second = self.source.with_name("0005.avi")
        second.write_bytes(self.source.read_bytes())
        self.workflow.prepare(second)
        self.assertEqual(self.client.get("/api/zone-assets").get_json()["assets"], [])
        self.assertEqual(self.client.post("/api/zone-assets/apply", json={"id": asset_id}).status_code, 400)

    def test_invalid_upload_and_missing_model(self):
        import io
        result = self.client.post("/api/videos", data={"video": (io.BytesIO(b"not a video"), "bad.mp4")})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(self.workflow.pointer.exists())
        self.select()
        self.assertEqual(self.client.post("/api/run/start").status_code, 400)

    def test_running_source_cannot_be_replaced(self):
        run = self.select()
        run["status"] = "running"
        write_json(self.workflow.runs / run["run_id"] / "run.json", run)
        entry = self.workflow.catalog()[0]
        result = self.client.post("/api/videos", json={"id": entry["id"]})
        self.assertEqual(result.status_code, 400)
        self.assertIn("Stop", result.get_json()["error"])

    def test_start_uses_current_dashboard_port_and_headless(self):
        self.select()
        model = self.workflow.edge / "baseline_yolo26n_best.onnx"
        model.touch()
        with patch("dashboard.workflow.subprocess.Popen") as process, patch("dashboard.workflow.threading.Thread"), patch("dashboard.workflow.importlib.metadata.version", return_value="8.4.56"):
            result = self.client.post("/api/run/start", environ_overrides={"SERVER_PORT": "5055"})
            self.assertEqual(result.status_code, 200)
            args = process.call_args.args[0]
            self.assertIn("http://127.0.0.1:5055/api/push-frame", args)
            self.assertIn("--headless", args)
            process.call_args.kwargs["stdout"].close()

    def test_start_rejects_incompatible_yolo_runtime(self):
        self.select()
        (self.workflow.edge / "baseline_yolo26n_best.onnx").touch()
        with patch("dashboard.workflow.importlib.metadata.version", return_value="8.3.240"), patch("dashboard.workflow.subprocess.Popen") as process:
            result = self.client.post("/api/run/start")
            self.assertEqual(result.status_code, 400)
            self.assertIn("8.3.240", result.get_json()["error"])
            process.assert_not_called()

    def test_event_history_and_zone_types_use_saved_rules(self):
        run = self.select()
        write_json(Path(run["zone_profile"]), {"zones": [{"id": "CUSTOM", "name": "Crane", "type": "danger_zone"}]})
        write_json(self.workflow.runs / run["run_id"] / "events.json", [{"timestamp": "2026-10-08T09:00:00", "camera_id": "0003", "zone_id": "CUSTOM", "alert_level": "CRITICAL"}])
        self.workflow.prepare(self.source)
        self.assertEqual(self.client.get("/api/events").get_json()["count"], 0)
        history = self.client.get("/api/events?scope=all").get_json()
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["events"][0]["zone_types"], ["danger_zone"])

    def test_runtime_stays_starting_until_first_detection(self):
        run = self.select()
        run["status"] = "starting"
        folder = self.workflow.runs / run["run_id"]
        write_json(folder / "run.json", run)
        write_json(folder / "progress.json", {"stage": "warming", "frame": 0})
        self.assertEqual(self.client.get("/api/run").get_json()["run"]["status"], "starting")
        write_json(folder / "progress.json", {"stage": "running", "frame": 7})
        result = self.client.get("/api/run").get_json()["run"]
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["progress"]["frame"], 7)
        self.assertEqual(self.client.get("/api/events").get_json()["count"], 0)

    def test_archive_keeps_zero_event_runs_and_downloads(self):
        run = self.select()
        folder = self.workflow.runs / run["run_id"]
        self.assertEqual(self.client.get("/api/runs").get_json()["runs"], [])
        run.update(status="completed", started_at="2026-10-09T10:00:00", return_code=0)
        write_json(folder / "run.json", run)
        (folder / "pipeline.log").write_text("Detector finished", encoding="utf-8")
        (folder / "output.mp4").write_bytes(b"test-video")
        (folder / "events.csv").write_text("timestamp,camera_id\n", encoding="utf-8")
        write_json(folder / "progress.json", {"frame": 3})
        result = self.client.get("/api/runs").get_json()["runs"][0]
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["frames"], 3)
        self.assertIn("video", result["files"])
        detail = self.client.get(f"/api/runs/{run['run_id']}").get_json()["run"]
        self.assertEqual(detail["log_tail"], "Detector finished")
        download = self.client.get(result["files"]["video"]["url"])
        self.assertEqual(download.data, b"test-video")
        self.assertIn("attachment", download.headers["Content-Disposition"])
        download.close()
        run["status"] = "running"
        write_json(folder / "run.json", run)
        self.assertEqual(self.client.get(result["files"]["video"]["url"]).status_code, 404)
        self.assertEqual(self.client.get(f"/api/runs/{run['run_id']}/files/secret").status_code, 404)
        self.assertEqual(self.client.get("/api/events?run_id=../secret").status_code, 404)

    def test_archive_filters_same_video_runs_and_preserves_zone_snapshot(self):
        run = self.select()
        folder = self.workflow.runs / run["run_id"]
        write_json(folder / "zones_snapshot.json", {"zones": [{"id": "CUSTOM", "name": "Original zone", "type": "danger_zone"}]})
        write_json(Path(run["zone_profile"]), {"zones": [{"id": "CUSTOM", "name": "Changed zone", "type": "warning_zone"}]})
        write_json(folder / "events.json", [{"timestamp": "2026-10-09T09:00:00", "camera_id": "0003", "zone_id": "CUSTOM", "alert_level": "CRITICAL"}])
        second = self.workflow.prepare(self.source)
        original = self.client.get(f"/api/events?run_id={run['run_id']}").get_json()
        self.assertEqual(original["count"], 1)
        self.assertEqual(original["events"][0]["zone"], "Original zone")
        self.assertEqual(original["events"][0]["run_id"], run["run_id"])
        self.assertEqual(self.client.get(f"/api/events?run_id={second['run_id']}").get_json()["count"], 0)

    def test_stream_falls_back_to_file_without_push(self):
        self.select()
        with patch.object(self.dashboard, "latest_live_frame", None):
            frames = self.dashboard.mjpeg_frames()
            self.assertIn(b"Content-Type: image/jpeg", next(frames))
            frames.close()

    def test_stop_requests_graceful_shutdown(self):
        from unittest.mock import Mock
        run = self.select()
        self.workflow.process = Mock()
        with patch("dashboard.workflow.threading.Thread"):
            self.workflow.stop()
        folder = self.workflow.runs / run["run_id"]
        self.assertTrue((folder / "stop.request").exists())
        self.workflow.process.terminate.assert_not_called()
        self.assertEqual(self.client.get("/api/run").get_json()["run"]["status"], "stopping")


if __name__ == "__main__":
    unittest.main()
