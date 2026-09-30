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


def _web_payload(**overrides):
    base = dict(
        front=_flat_grid(1800),
        down=_flat_grid(2000),
        left_mm=850,
        right_mm=1180,
        angle=56.0,
        rate=3.1,
        bias_dps=0.42,
        safety_events=[],
        blocked=False,
        avoidance_angle=None,
        haptic_status="시스템 준비 중",
    )
    base.update(overrides)
    return hardware_main._web_dashboard_payload(**base)


class WebDashboardPayloadTests(unittest.TestCase):
    def test_matches_the_shape_web_app_js_expects(self):
        payload = _web_payload()

        self.assertEqual(set(payload.keys()), {"stats", "imu", "tof", "decisions"})
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
        self.assertEqual(payload["imu"], {"direction": "RIGHT", "angleDeg": 56.0})

    def test_flat_64_cell_grid_is_reshaped_to_8x8(self):
        payload = _web_payload(front=list(range(64)))

        front_grid = payload["tof"]["front"]
        self.assertEqual(len(front_grid), 8)
        self.assertTrue(all(len(row) == 8 for row in front_grid))
        self.assertEqual(front_grid[0], [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(front_grid[7], [56, 57, 58, 59, 60, 61, 62, 63])

    def test_negative_angle_is_left_direction(self):
        payload = _web_payload(angle=-42.0)

        self.assertEqual(payload["imu"]["direction"], "LEFT")

    def test_invalid_tof_cells_stay_null(self):
        front = _flat_grid()
        front[10] = None

        payload = _web_payload(front=front)

        self.assertIsNone(payload["tof"]["front"][1][2])  # index 10 = row1,col2


class WebDashboardDecisionsTests(unittest.TestCase):
    def test_decisions_has_four_labeled_rows_in_order(self):
        payload = _web_payload()

        labels = [row["label"] for row in payload["decisions"]]
        self.assertEqual(labels, ["장애물", "계단/낙차", "회피 결정", "팔찌 진동"])

    def test_matches_terminal_dashboard_labels_for_the_same_inputs(self):
        # 웹과 터미널이 같은 입력에 같은 문구를 써야 한다 — 라벨 계산 로직이 하나로
        # 공유되는지(_obstacle_stairs_avoidance_labels) 확인한다.
        stairs_event = [WaybandEvent(EventKind.STAIR_DOWN, "DOWN_TOF")]

        terminal = hardware_main._dashboard_payload(
            front=_flat_grid(),
            down=_flat_grid(),
            left_mm=850,
            right_mm=1180,
            angle=0.0,
            rate=0.0,
            safety_events=stairs_event,
            blocked=True,
            avoidance_angle=-12.0,
            action="회피 회전 진행 중",
            simulated=False,
            front_enabled=True,
        )
        web = _web_payload(
            safety_events=stairs_event,
            blocked=True,
            avoidance_angle=-12.0,
            haptic_status="회피 회전 진행 중",
        )

        by_label = {row["label"]: row["value"] for row in web["decisions"]}
        self.assertEqual(by_label["장애물"], terminal["obstacle"])
        self.assertEqual(by_label["계단/낙차"], terminal["stairs"])
        self.assertEqual(by_label["회피 결정"], terminal["avoidance"])
        self.assertEqual(by_label["팔찌 진동"], terminal["haptic_status"])

    def test_haptic_status_passes_through_verbatim(self):
        payload = _web_payload(haptic_status="하행 계단 진동 전송 완료")

        by_label = {row["label"]: row["value"] for row in payload["decisions"]}
        self.assertEqual(by_label["팔찌 진동"], "하행 계단 진동 전송 완료")


if __name__ == "__main__":
    unittest.main()
