import csv
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import demo


class DemoWorkflowTests(unittest.TestCase):
    def test_zone_profile_must_match_video_resolution(self):
        source = Path(
            "edge-pipeline/media/videos/input/demo_video3.mp4"
        ).resolve()
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "demo_video3.json"
            profile.write_text(
                json.dumps(
                    {
                        "source": source.name,
                        "width": 1280,
                        "height": 720,
                        "zones": [],
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(demo.zone_profile_matches(profile, source))

            profile.write_text(
                json.dumps(
                    {
                        "source": source.name,
                        "width": 1920,
                        "height": 1080,
                        "zones": [],
                    }
                ),
                encoding="utf-8",
            )
            self.assertFalse(demo.zone_profile_matches(profile, source))

    def test_pipeline_command_includes_session_test_options(self):
        args = SimpleNamespace(
            camera_id="CAM-02",
            conf=0.4,
            iou=0.45,
            smooth=5,
            inference_interval=3,
            alert_cooldown=5.0,
            live_preview_fps=20.0,
            headless=True,
            max_frames=25,
            no_dashboard=False,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("demo.subprocess.run") as run_mock:
                run_mock.return_value.returncode = 0
                result = demo.run_pipeline(
                    root / "video.mp4",
                    root / "model.onnx",
                    root / "zones.json",
                    root / "run",
                    args,
                )

            command = run_mock.call_args.args[0]
            self.assertEqual(result, 0)
            self.assertIn("--headless", command)
            self.assertIn("--max-frames", command)
            self.assertIn("25", command)
            self.assertIn("--log-dir", command)
            self.assertIn("--camera-id", command)
            self.assertIn("CAM-02", command)
            self.assertIn("--inference-interval", command)
            self.assertIn("3", command)
            self.assertIn("--alert-cooldown", command)
            self.assertIn("5.0", command)
            self.assertIn("--live-frame", command)
            self.assertIn("--live-preview-fps", command)
            self.assertIn("20.0", command)
            self.assertIn("--frame-push-url", command)
            self.assertIn("http://127.0.0.1:5000/api/push-frame", command)

    def test_created_run_becomes_dashboard_active_run(self):
        dashboard_module = importlib.import_module("dashboard.app")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            logs_dir = root / "logs"
            runs_dir = logs_dir / "runs"
            active_path = logs_dir / "active_run.json"
            source = root / "site_demo.mp4"
            model = root / "model.onnx"
            zones = root / "site_demo.json"
            source.touch()
            model.touch()
            zones.write_text(
                json.dumps({"source": source.name, "zones": []}),
                encoding="utf-8",
            )

            original_demo_runs = demo.RUNS_DIR
            original_demo_active = demo.ACTIVE_RUN_PATH
            original_dashboard_runs = dashboard_module.RUNS_DIR
            original_dashboard_active = dashboard_module.ACTIVE_RUN_PATH
            try:
                demo.RUNS_DIR = runs_dir
                demo.ACTIVE_RUN_PATH = active_path
                dashboard_module.RUNS_DIR = runs_dir
                dashboard_module.ACTIVE_RUN_PATH = active_path

                args = SimpleNamespace(
                    camera_id="CAM-TEST",
                    headless=True,
                    max_frames=10,
                    conf=0.4,
                    iou=0.45,
                    smooth=5,
                    inference_interval=3,
                    alert_cooldown=5.0,
                    live_preview_fps=20.0,
                    no_dashboard=False,
                )
                run_dir, metadata = demo.create_run(source, model, zones, args)
                (run_dir / "live_frame.jpg").write_bytes(b"\xff\xd8\xff\xd9")

                with (run_dir / "events.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=[
                            "timestamp",
                            "camera_id",
                            "zone_id",
                            "alert_level",
                            "violation_type",
                            "confidence",
                            "bbox",
                            "snapshot_path",
                        ],
                    )
                    writer.writeheader()
                    writer.writerow(
                        {
                            "timestamp": "2026-06-19 09:00:00",
                            "camera_id": "CAM-TEST",
                            "zone_id": "Z01",
                            "alert_level": "CRITICAL",
                            "violation_type": "no_helmet",
                            "confidence": "0.91",
                            "bbox": "[1, 2, 3, 4]",
                            "snapshot_path": "None",
                        }
                    )

                client = dashboard_module.app.test_client()
                run_payload = client.get("/api/run").get_json()
                events_payload = client.get("/api/events").get_json()
                stats_payload = client.get("/api/stats").get_json()
                live_response = client.get("/api/live-frame")
                push_response = client.post(
                    "/api/push-frame",
                    data=b"\xff\xd8\xff\xd9",
                    content_type="image/jpeg",
                )

                self.assertTrue(run_payload["active"])
                self.assertEqual(run_payload["run"]["run_id"], metadata["run_id"])
                self.assertEqual(events_payload["count"], 1)
                self.assertEqual(
                    events_payload["events"][0]["camera_id"], "CAM-TEST"
                )
                self.assertEqual(stats_payload["live_frame_url"], "/api/live-frame")
                self.assertEqual(live_response.status_code, 200)
                self.assertIn("no-store", live_response.headers["Cache-Control"])
                self.assertEqual(push_response.status_code, 200)
                self.assertTrue(push_response.get_json()["ok"])
                feed = dashboard_module.mjpeg_frames()
                try:
                    chunk = next(feed)
                finally:
                    feed.close()
                self.assertIn(b"Content-Type: image/jpeg", chunk)
                self.assertIn(b"\xff\xd8\xff\xd9", chunk)
                live_response.close()
            finally:
                demo.RUNS_DIR = original_demo_runs
                demo.ACTIVE_RUN_PATH = original_demo_active
                dashboard_module.RUNS_DIR = original_dashboard_runs
                dashboard_module.ACTIVE_RUN_PATH = original_dashboard_active


if __name__ == "__main__":
    unittest.main()
