import importlib
import json
import tempfile
import unittest
from pathlib import Path


class DashboardZoneApiTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = importlib.import_module("dashboard.app")
        self.original_runs = self.dashboard.RUNS_DIR
        self.original_active = self.dashboard.ACTIVE_RUN_PATH
        self.original_zones = self.dashboard.ZONES_DIR
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        runs = root / "logs" / "runs"
        run_dir = runs / "run-001"
        zones = root / "configs" / "zones"
        run_dir.mkdir(parents=True)
        zones.mkdir(parents=True)
        zone_path = zones / "camera-a.json"
        zone_path.write_text(
            json.dumps(
                {
                    "source": "camera-a.mp4",
                    "width": 1280,
                    "height": 720,
                    "zones": [
                        {
                            "id": "Z01",
                            "name": "Danger Zone",
                            "type": "danger_zone",
                            "polygon": [[100, 100], [500, 100], [500, 500]],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "run_id": "run-001",
                    "status": "completed",
                    "source_name": "camera-a.mp4",
                    "zone_profile": str(zone_path),
                }
            ),
            encoding="utf-8",
        )
        active = root / "logs" / "active_run.json"
        active.write_text(json.dumps({"run_dir": str(run_dir)}), encoding="utf-8")
        self.dashboard.RUNS_DIR = runs
        self.dashboard.ACTIVE_RUN_PATH = active
        self.dashboard.ZONES_DIR = zones
        self.zone_path = zone_path
        self.client = self.dashboard.app.test_client()

    def tearDown(self):
        self.dashboard.RUNS_DIR = self.original_runs
        self.dashboard.ACTIVE_RUN_PATH = self.original_active
        self.dashboard.ZONES_DIR = self.original_zones
        self.temporary.cleanup()

    def test_zone_editor_page_and_profile_are_available(self):
        self.assertEqual(self.client.get("/zones").status_code, 200)
        response = self.client.get("/api/zones")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["profile"]["width"], 1280)
        self.assertEqual(payload["profile"]["zones"][0]["id"], "Z01")

    def test_valid_profile_is_saved_atomically_with_backup(self):
        payload = {
            "width": 1280,
            "height": 720,
            "zones": [
                {
                    "id": "Z02",
                    "name": "Warning Zone",
                    "type": "warning_zone",
                    "polygon": [[20, 20], [420, 20], [420, 320], [20, 320]],
                }
            ],
        }
        response = self.client.post("/api/zones", json=payload)
        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.zone_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["source"], "camera-a.mp4")
        self.assertEqual(saved["zones"][0]["id"], "Z02")
        self.assertTrue(self.zone_path.with_suffix(".json.bak").is_file())

    def test_invalid_polygon_is_rejected_without_overwriting_profile(self):
        original = self.zone_path.read_text(encoding="utf-8")
        response = self.client.post(
            "/api/zones",
            json={
                "width": 1280,
                "height": 720,
                "zones": [
                    {
                        "id": "Z99",
                        "name": "Broken",
                        "type": "danger_zone",
                        "polygon": [[0, 0], [1400, 10], [30, 40]],
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.zone_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
