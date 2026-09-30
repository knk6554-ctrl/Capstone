import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "hardware" / "real"
if str(REAL_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_DIR))

import demo_obstacle_avoidance as demo  # noqa: E402
from config import Config  # noqa: E402


class DecideNextStepTests(unittest.TestCase):
    def test_walking_stays_walking_while_front_is_clear(self):
        step = demo.decide_next_step(
            demo.DemoPhase.WALKING, blocked=False, left_mm=1800, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(step.phase, demo.DemoPhase.WALKING)
        self.assertEqual(step.action, demo.DemoAction.NONE)

    def test_front_obstacle_moves_to_checking_left_with_warning(self):
        step = demo.decide_next_step(
            demo.DemoPhase.WALKING, blocked=True, left_mm=1800, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(step.phase, demo.DemoPhase.CHECKING_LEFT)
        self.assertEqual(step.action, demo.DemoAction.FRONT_WARNING)

    def test_left_clear_turns_left_without_checking_right(self):
        step = demo.decide_next_step(
            demo.DemoPhase.CHECKING_LEFT,
            blocked=True,
            left_mm=1800,
            right_mm=400,  # 오른쪽이 막혀 있어도 왼쪽이 열려 있으면 오른쪽은 보지 않는다
            side_clear_mm=650,
        )

        self.assertEqual(step.phase, demo.DemoPhase.MOVING)
        self.assertEqual(step.action, demo.DemoAction.TURN_LEFT)

    def test_left_blocked_moves_to_checking_right(self):
        step = demo.decide_next_step(
            demo.DemoPhase.CHECKING_LEFT, blocked=True, left_mm=400, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(step.phase, demo.DemoPhase.CHECKING_RIGHT)
        self.assertEqual(step.action, demo.DemoAction.NONE)

    def test_left_blocked_then_right_clear_turns_right(self):
        # 시연 시나리오 그대로: 왼쪽 막힘 -> 오른쪽 확인 -> 오른쪽 열림 -> 우회전.
        step = demo.decide_next_step(
            demo.DemoPhase.CHECKING_RIGHT, blocked=True, left_mm=400, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(step.phase, demo.DemoPhase.MOVING)
        self.assertEqual(step.action, demo.DemoAction.TURN_RIGHT)

    def test_both_sides_blocked_stops(self):
        step = demo.decide_next_step(
            demo.DemoPhase.CHECKING_RIGHT, blocked=True, left_mm=400, right_mm=400, side_clear_mm=650
        )

        self.assertEqual(step.phase, demo.DemoPhase.BLOCKED)
        self.assertEqual(step.action, demo.DemoAction.NO_PATH)

    def test_missing_side_reading_is_treated_as_clear(self):
        # ToF가 못 읽은(None) 쪽은 "막혔다"고 단정하지 않고 열린 걸로 본다 —
        # 실제로는 유효 범위(0~4000mm) 밖이라 못 읽었을 뿐일 수 있어서다.
        step = demo.decide_next_step(
            demo.DemoPhase.CHECKING_LEFT, blocked=True, left_mm=None, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(step.action, demo.DemoAction.TURN_LEFT)

    def test_moving_and_blocked_are_terminal(self):
        moving = demo.decide_next_step(
            demo.DemoPhase.MOVING, blocked=False, left_mm=1800, right_mm=1800, side_clear_mm=650
        )
        blocked = demo.decide_next_step(
            demo.DemoPhase.BLOCKED, blocked=False, left_mm=1800, right_mm=1800, side_clear_mm=650
        )

        self.assertEqual(moving.phase, demo.DemoPhase.MOVING)
        self.assertEqual(blocked.phase, demo.DemoPhase.BLOCKED)


class DemoScenarioRigTests(unittest.TestCase):
    def test_starts_all_clear(self):
        cfg = Config()
        rig = demo.DemoScenarioRig(cfg, obstacle_after_seconds=3.0)
        with patch("demo_obstacle_avoidance.time.monotonic", side_effect=[0.0, 0.0]):
            rig.start()
            front, _down, left_mm, right_mm = rig.snapshot()

        self.assertTrue(all(value == 1800 for value in front))
        self.assertEqual(left_mm, 1800)
        self.assertEqual(right_mm, 1800)

    def test_obstacle_appears_with_left_blocked_and_right_clear_after_the_delay(self):
        cfg = Config()
        rig = demo.DemoScenarioRig(cfg, obstacle_after_seconds=3.0)
        with patch("demo_obstacle_avoidance.time.monotonic", side_effect=[0.0, 5.0]):
            rig.start()
            front, _down, left_mm, right_mm = rig.snapshot()

        self.assertEqual(left_mm, 400)
        self.assertEqual(right_mm, 1800)
        # 전방 중앙 블록이 실제로 front_is_blocked() 임계값에 걸리는지도 확인한다.
        from control import front_is_blocked

        self.assertTrue(front_is_blocked(front, cfg.front_warning_mm))


if __name__ == "__main__":
    unittest.main()
