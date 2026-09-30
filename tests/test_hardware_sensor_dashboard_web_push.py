import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "hardware" / "real"
if str(REAL_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_DIR))

import sensor_dashboard  # noqa: E402


def _sensor_payload(**overrides):
    base = {
        "left_mm": 850,
        "right_mm": 1180,
        "angle_deg": 0.0,
        "rate_dps": 0.0,
        "front": list(range(64)),
        "down": [700] * 64,
        "counts": {"normal": 4, "warning": 0, "danger": 0},
    }
    base.update(overrides)
    return base


class WebDashboardPayloadTests(unittest.TestCase):
    def test_matches_the_shape_web_app_js_expects(self):
        payload = sensor_dashboard._web_dashboard_payload(_sensor_payload(), bias_dps=0.42)

        self.assertEqual(set(payload.keys()), {"stats", "statusSummary", "imu", "tof"})
        self.assertEqual(payload["stats"]["leftSideMm"], 850)
        self.assertEqual(payload["stats"]["gyroZOffsetDegPerSec"], 0.42)
        self.assertEqual(len(payload["statusSummary"]), 3)

    def test_normal_warning_danger_counts_map_to_good_warning_critical(self):
        payload = sensor_dashboard._web_dashboard_payload(
            _sensor_payload(counts={"normal": 1, "warning": 2, "danger": 3}), bias_dps=0.0
        )

        by_level = {item["level"]: item["count"] for item in payload["statusSummary"]}
        self.assertEqual(by_level, {"good": 1, "warning": 2, "critical": 3})

    def test_flat_64_cell_grid_is_reshaped_to_8x8(self):
        payload = sensor_dashboard._web_dashboard_payload(_sensor_payload(), bias_dps=0.0)

        front_grid = payload["tof"]["front"]
        self.assertEqual(len(front_grid), 8)
        self.assertTrue(all(len(row) == 8 for row in front_grid))
        self.assertEqual(front_grid[0], [0, 1, 2, 3, 4, 5, 6, 7])

    def test_negative_angle_is_left_direction(self):
        payload = sensor_dashboard._web_dashboard_payload(
            _sensor_payload(angle_deg=-30.0), bias_dps=0.0
        )

        self.assertEqual(payload["imu"]["direction"], "LEFT")

    def test_positive_angle_is_right_direction(self):
        payload = sensor_dashboard._web_dashboard_payload(
            _sensor_payload(angle_deg=30.0), bias_dps=0.0
        )

        self.assertEqual(payload["imu"]["direction"], "RIGHT")


if __name__ == "__main__":
    unittest.main()
