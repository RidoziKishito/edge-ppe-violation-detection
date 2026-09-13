import unittest
import sys
import os

# Point path one level up to import rule_engine
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rule_engine


class TestRuleEngine(unittest.TestCase):
    def setUp(self):
        # Mock data for zones
        self.zones_config = {
            "zones": [
                {
                    "id": "Z_DANGER",
                    "type": "danger_zone",
                    "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
                }
            ]
        }

    def test_point_in_polygon(self):
        # Point (5,5) is inside 10x10 box -> should return True
        self.assertTrue(
            rule_engine.point_in_polygon(
                (5, 5), self.zones_config["zones"][0]["polygon"]
            )
        )
        # Point (15,15) is outside the box -> should return False
        self.assertFalse(
            rule_engine.point_in_polygon(
                (15, 15), self.zones_config["zones"][0]["polygon"]
            )
        )

    def test_critical_alert_in_danger_zone(self):
        active_zones = rule_engine.get_person_zones((5, 5), self.zones_config)
        violations = ["no_helmet"]  # Simulate missing helmet
        alert = rule_engine.classify_alert(active_zones, violations)
        # Standing in Danger Zone should be CRITICAL
        self.assertEqual(alert, "CRITICAL")

    def test_normal_alert_outside_zone(self):
        active_zones = rule_engine.get_person_zones((15, 15), self.zones_config)
        violations = []  # All PPE present
        alert = rule_engine.classify_alert(active_zones, violations)
        # Outside zone with full PPE should be NORMAL
        self.assertEqual(alert, "NORMAL")


if __name__ == "__main__":
    unittest.main()
