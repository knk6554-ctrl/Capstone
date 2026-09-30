import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "hardware" / "real"
if str(REAL_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_DIR))

import control  # noqa: E402
from wayband_hw.core.events import Side  # noqa: E402
from wayband_hw.drivers.gpio_wrist import GpioWristController  # noqa: E402


class FakeWrists:
    def __init__(self):
        self.sent = []
        self.stopped = 0

    async def send(self, pattern):
        self.sent.append(pattern)

    async def stop(self):
        self.stopped += 1


class ScriptedImu:
    """update()가 호출될 때마다 미리 정해둔 각도를 순서대로 돌려주다가 마지막 값을 유지한다."""

    def __init__(self, angles):
        self._angles = list(angles)
        self._index = 0
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1

    def update(self):
        angle = self._angles[min(self._index, len(self._angles) - 1)]
        self._index += 1
        return angle, 0.0


class RotationControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tiny_angle_is_a_no_op_success(self):
        wrists = FakeWrists()
        controller = control.RotationController(wrists, ScriptedImu([0.0]), timeout_seconds=1.0)

        ok = await controller.rotate(0.5)

        self.assertTrue(ok)
        self.assertEqual(wrists.sent, [])

    async def test_simulate_mode_always_succeeds_with_directional_pulse(self):
        wrists = FakeWrists()
        controller = control.RotationController(
            wrists, ScriptedImu([0.0]), simulate=True, timeout_seconds=1.0
        )

        ok = await controller.rotate(-45.0)

        self.assertTrue(ok)
        self.assertEqual(len(wrists.sent), 1)
        self.assertEqual(wrists.sent[0].side, Side.LEFT)

    async def test_overshooting_target_returns_immediately(self):
        wrists = FakeWrists()
        imu = ScriptedImu([90.0])  # 첫 프레임부터 목표(87도)를 넘어선다
        controller = control.RotationController(
            wrists, imu, tolerance_degrees=4.0, timeout_seconds=2.0
        )

        ok = await controller.rotate(87.0)

        self.assertTrue(ok)
        self.assertEqual(imu.reset_calls, 1)
        self.assertGreaterEqual(wrists.stopped, 1)

    async def test_holding_within_tolerance_band_completes(self):
        wrists = FakeWrists()
        imu = ScriptedImu([85.0])  # 목표(87도) 오차(4도) 안이지만 넘지는 않는다
        controller = control.RotationController(
            wrists, imu, tolerance_degrees=4.0, timeout_seconds=2.0
        )

        ok = await controller.rotate(87.0)

        self.assertTrue(ok)

    async def test_gives_up_after_timeout_without_reaching_angle(self):
        wrists = FakeWrists()
        imu = ScriptedImu([0.0])  # 전혀 돌지 않는 상황(센서 오류·미동 등)
        controller = control.RotationController(
            wrists, imu, tolerance_degrees=4.0, timeout_seconds=0.05
        )

        ok = await controller.rotate(87.0)

        self.assertFalse(ok)
        self.assertGreaterEqual(wrists.stopped, 1)

    async def test_gpio_wrist_stops_early_instead_of_riding_out_the_full_timeout(self):
        # 회귀 테스트: GpioWristController.send()가 펄스가 끝날 때까지 블로킹하던
        # 시절에는, rotate()가 send()에서 timeout_seconds(여기선 5초) 전체를 그냥
        # 기다린 뒤에야 IMU 폴링 루프에 들어갔다 — "목표각 도달 시 정지"가 전혀
        # 동작하지 않았다. 지금은 send()가 즉시 반환하고 IMU가 목표를 확인하는
        # 즉시 stop()으로 끊어야 하므로, 훨씬 빨리 끝나야 한다.
        wrists = GpioWristController(simulate=True)
        imu = ScriptedImu([90.0])  # 첫 프레임부터 목표(87도)를 넘어선다
        controller = control.RotationController(
            wrists, imu, tolerance_degrees=4.0, timeout_seconds=5.0
        )

        started = time.monotonic()
        ok = await controller.rotate(87.0)
        elapsed = time.monotonic() - started

        self.assertTrue(ok)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(wrists.motors[Side.RIGHT].calls[-1], ("off", 0.0))


def _front_grid(default_mm=2000, near_columns=(), near_mm=500):
    grid = [default_mm] * 64
    for row in range(2, 7):
        for column in near_columns:
            grid[row * 8 + column] = near_mm
    return grid


class FrontIsBlockedTests(unittest.TestCase):
    def test_all_clear_is_not_blocked(self):
        self.assertFalse(control.front_is_blocked(_front_grid()))

    def test_two_adjacent_near_columns_is_blocked(self):
        self.assertTrue(control.front_is_blocked(_front_grid(near_columns=(3, 4))))

    def test_single_isolated_near_column_is_not_blocked(self):
        self.assertFalse(control.front_is_blocked(_front_grid(near_columns=(3,))))


class PlanAvoidanceAngleTests(unittest.TestCase):
    def test_no_obstacle_returns_zero(self):
        angle = control.plan_avoidance_angle(_front_grid(), 1800, 1800)
        self.assertEqual(angle, 0.0)

    def test_obstacle_on_left_escapes_right(self):
        front = _front_grid(near_columns=(0, 1, 2, 3))
        angle = control.plan_avoidance_angle(front, 1800, 1800)
        self.assertIsNotNone(angle)
        self.assertGreater(angle, 0)

    def test_obstacle_on_right_escapes_left(self):
        front = _front_grid(near_columns=(4, 5, 6, 7))
        angle = control.plan_avoidance_angle(front, 1800, 1800)
        self.assertIsNotNone(angle)
        self.assertLess(angle, 0)

    def test_fully_blocked_with_no_corridor_returns_none(self):
        front = _front_grid(default_mm=500, near_columns=range(8))
        angle = control.plan_avoidance_angle(front, 1800, 1800)
        self.assertIsNone(angle)


if __name__ == "__main__":
    unittest.main()
