import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "hardware" / "real"
if str(REAL_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_DIR))

# test_hardware_main.py와 같은 방식으로 로드한다 — 흔한 이름인 "main"으로 바로
# import하면 다른 테스트 모듈과 충돌할 수 있어 고유한 이름을 붙여 로드한다.
spec = importlib.util.spec_from_file_location("wayband_hardware_main", REAL_DIR / "main.py")
hardware_main = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hardware_main)

from wayband_hw.core.events import EventKind, WaybandEvent  # noqa: E402


def _flat_grid(value=1800):
    return [value] * 64


class WebDashboardStatLevelsTests(unittest.TestCase):
    def test_all_clear_is_all_good(self):
        levels = hardware_main._web_dashboard_stat_levels(
            blocked=False, safety_events=[], left_mm=1800, right_mm=1800, side_clear_mm=650
        )
        self.assertEqual(levels, ["good", "good", "good", "good"])

    def test_blocked_marks_front_critical(self):
        levels = hardware_main._web_dashboard_stat_levels(
            blocked=True, safety_events=[], left_mm=1800, right_mm=1800, side_clear_mm=650
        )
        self.assertEqual(levels[0], "critical")

    def test_down_danger_is_critical_but_stair_up_is_only_warning(self):
        drop = [WaybandEvent(EventKind.DOWN_DANGER, "DOWN_TOF")]
        stairs = [WaybandEvent(EventKind.STAIR_UP, "FRONT_DOWN_TOF")]

        levels_drop = hardware_main._web_dashboard_stat_levels(
            blocked=False, safety_events=drop, left_mm=1800, right_mm=1800, side_clear_mm=650
        )
        levels_stairs = hardware_main._web_dashboard_stat_levels(
            blocked=False, safety_events=stairs, left_mm=1800, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(levels_drop[1], "critical")
        self.assertEqual(levels_stairs[1], "warning")

    def test_side_proximity_marks_warning(self):
        levels = hardware_main._web_dashboard_stat_levels(
            blocked=False, safety_events=[], left_mm=400, right_mm=400, side_clear_mm=650
        )
        self.assertEqual(levels[2], "warning")
        self.assertEqual(levels[3], "warning")


class WebDashboardPayloadTests(unittest.TestCase):
    def test_matches_the_shape_web_app_js_expects(self):
        payload = hardware_main._web_dashboard_payload(
            front=_flat_grid(1800),
            down=_flat_grid(2000),
            left_mm=850,
            right_mm=1180,
            angle=56.0,
            rate=3.1,
            bias_dps=0.42,
            safety_events=[],
            blocked=False,
            side_clear_mm=650,
        )

        self.assertEqual(
            set(payload.keys()), {"stats", "statusSummary", "imu", "tof"}
        )
        self.assertEqual(
            set(payload["stats"].keys()),
            {
                "leftSideMm",
                "rightSideMm",
                "rotationDeg",
                "gyroZOffsetDegPerSec",
                "gyroZFinalDegPerSec",
            },
        )
        self.assertEqual(payload["stats"]["leftSideMm"], 850)
        self.assertEqual(payload["stats"]["gyroZOffsetDegPerSec"], 0.42)
        self.assertEqual(len(payload["statusSummary"]), 3)
        self.assertEqual(payload["imu"], {"direction": "RIGHT", "angleDeg": 56.0})

    def test_flat_64_cell_grid_is_reshaped_to_8x8(self):
        flat = list(range(64))

        payload = hardware_main._web_dashboard_payload(
            front=flat,
            down=_flat_grid(),
            left_mm=1800,
            right_mm=1800,
            angle=0.0,
            rate=0.0,
            bias_dps=0.0,
            safety_events=[],
            blocked=False,
            side_clear_mm=650,
        )

        front_grid = payload["tof"]["front"]
        self.assertEqual(len(front_grid), 8)
        self.assertTrue(all(len(row) == 8 for row in front_grid))
        self.assertEqual(front_grid[0], [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(front_grid[7], [56, 57, 58, 59, 60, 61, 62, 63])

    def test_negative_angle_is_left_direction(self):
        payload = hardware_main._web_dashboard_payload(
            front=_flat_grid(),
            down=_flat_grid(),
            left_mm=1800,
            right_mm=1800,
            angle=-42.0,
            rate=0.0,
            bias_dps=0.0,
            safety_events=[],
            blocked=False,
            side_clear_mm=650,
        )

        self.assertEqual(payload["imu"]["direction"], "LEFT")

    def test_invalid_tof_cells_stay_null(self):
        front = _flat_grid()
        front[10] = None

        payload = hardware_main._web_dashboard_payload(
            front=front,
            down=_flat_grid(),
            left_mm=1800,
            right_mm=1800,
            angle=0.0,
            rate=0.0,
            bias_dps=0.0,
            safety_events=[],
            blocked=False,
            side_clear_mm=650,
        )

        self.assertIsNone(payload["tof"]["front"][1][2])  # index 10 = row1,col2


if __name__ == "__main__":
    unittest.main()
