import unittest

from belt.imu import ScriptedImu
from belt.motors import NullMotor
from belt.pattern_player import PatternPlayer, build_pulse_plan, motors_for_target


def _command(**overrides):
    base = {
        "target": "RIGHT_WRIST",
        "pattern": "TURN_NOW",
        "intensity": 0.9,
        "pulseCount": 3,
        "pulseOnMs": 220,
        "pulseOffMs": 180,
    }
    base.update(overrides)
    return base


class BuildPulsePlanTests(unittest.TestCase):
    def test_last_pulse_has_no_trailing_off(self):
        plan = build_pulse_plan(3, 220, 180)

        self.assertEqual(len(plan), 3)
        self.assertEqual([p.on_ms for p in plan], [220, 220, 220])
        self.assertEqual([p.off_ms for p in plan], [180, 180, 0])

    def test_single_pulse_has_no_off(self):
        plan = build_pulse_plan(1, 220, 180)

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].off_ms, 0)

    def test_zero_count_is_empty(self):
        self.assertEqual(build_pulse_plan(0, 220, 180), ())

    def test_clamps_runaway_values_for_motor_safety(self):
        plan = build_pulse_plan(999, 999_999, 999_999)

        self.assertLessEqual(len(plan), 20)
        self.assertTrue(all(p.on_ms <= 2000 for p in plan))


class MotorsForTargetTests(unittest.TestCase):
    def test_both_wrists_maps_to_two_motors(self):
        self.assertEqual(
            motors_for_target("BOTH_WRISTS"), ("LEFT_WRIST", "RIGHT_WRIST")
        )

    def test_single_target_maps_to_one_motor(self):
        self.assertEqual(motors_for_target("LEFT_WRIST"), ("LEFT_WRIST",))

    def test_unknown_target_raises(self):
        with self.assertRaises(ValueError):
            motors_for_target("NOT_A_TARGET")


class PatternPlayerTests(unittest.TestCase):
    def _play(self, command, motor_names):
        sleeps: list[float] = []
        motors = {name: NullMotor(name) for name in motor_names}
        player = PatternPlayer(motors, sleep=sleeps.append)
        player.play(command)
        return motors, sleeps

    def test_turn_now_pulses_one_wrist_three_times(self):
        motors, sleeps = self._play(_command(), ["LEFT_WRIST", "RIGHT_WRIST"])

        right_calls = motors["RIGHT_WRIST"].calls
        self.assertEqual(
            right_calls,
            [
                ("on", 0.9),
                ("off", 0.0),
                ("on", 0.9),
                ("off", 0.0),
                ("on", 0.9),
                ("off", 0.0),
            ],
        )
        self.assertEqual(motors["LEFT_WRIST"].calls, [])
        # 3회 on(220ms) + 2회 off(180ms) 간격만 sleep한다(마지막 off는 없음).
        self.assertEqual(sleeps, [0.22, 0.18, 0.22, 0.18, 0.22])

    def test_both_wrists_pulse_together(self):
        motors, _sleeps = self._play(
            _command(target="BOTH_WRISTS", pulseCount=1, pulseOnMs=700, pulseOffMs=250),
            ["LEFT_WRIST", "RIGHT_WRIST"],
        )

        self.assertEqual(motors["LEFT_WRIST"].calls, [("on", 0.9), ("off", 0.0)])
        self.assertEqual(motors["RIGHT_WRIST"].calls, [("on", 0.9), ("off", 0.0)])

    def test_obstacle_command_drives_belt_motor(self):
        motors, _sleeps = self._play(
            _command(
                target="BELT_FRONT_LEFT",
                pattern="OBSTACLE_CRITICAL",
                intensity=1.0,
                pulseCount=5,
                pulseOnMs=180,
                pulseOffMs=100,
            ),
            ["BELT_FRONT_LEFT"],
        )

        self.assertEqual(len(motors["BELT_FRONT_LEFT"].calls), 10)

    def test_missing_motor_is_skipped_without_error(self):
        motors, sleeps = self._play(_command(target="LEFT_WRIST"), ["RIGHT_WRIST"])

        self.assertEqual(sleeps, [])
        self.assertEqual(motors["RIGHT_WRIST"].calls, [])


class CanPlayTurnTests(unittest.TestCase):
    def test_turn_now_with_angle_and_imu_is_continuous(self):
        motors = {"RIGHT_WRIST": NullMotor("RIGHT_WRIST")}
        player = PatternPlayer(motors, imu=ScriptedImu([90.0]))

        self.assertTrue(
            player.can_play_turn(_command(pattern="TURN_NOW", targetAngleDegrees=87.0))
        )

    def test_prepare_turn_is_never_continuous_even_with_angle(self):
        motors = {"RIGHT_WRIST": NullMotor("RIGHT_WRIST")}
        player = PatternPlayer(motors, imu=ScriptedImu([90.0]))

        self.assertFalse(
            player.can_play_turn(
                _command(pattern="PREPARE_TURN", targetAngleDegrees=87.0)
            )
        )

    def test_turn_now_without_imu_falls_back_to_fixed_pulses(self):
        motors = {"RIGHT_WRIST": NullMotor("RIGHT_WRIST")}
        player = PatternPlayer(motors, imu=None)

        self.assertFalse(
            player.can_play_turn(_command(pattern="TURN_NOW", targetAngleDegrees=87.0))
        )

    def test_turn_now_without_angle_falls_back_to_fixed_pulses(self):
        # crosswalk/stairs/arrived처럼 targetAngleDegrees가 없는 명령.
        motors = {"RIGHT_WRIST": NullMotor("RIGHT_WRIST")}
        player = PatternPlayer(motors, imu=ScriptedImu([90.0]))

        self.assertFalse(
            player.can_play_turn(
                _command(pattern="TURN_NOW", targetAngleDegrees=None)
            )
        )

    def test_play_turn_command_drives_correct_wrist_until_angle_reached(self):
        motors = {
            "LEFT_WRIST": NullMotor("LEFT_WRIST"),
            "RIGHT_WRIST": NullMotor("RIGHT_WRIST"),
        }
        player = PatternPlayer(
            motors, imu=ScriptedImu([90.0]), sleep=lambda _seconds: None
        )

        result = player.play_turn_command(
            _command(target="RIGHT_WRIST", pattern="TURN_NOW", targetAngleDegrees=87.0)
        )

        self.assertTrue(result.completed)
        self.assertEqual(motors["LEFT_WRIST"].calls, [])
        self.assertTrue(motors["RIGHT_WRIST"].calls)


if __name__ == "__main__":
    unittest.main()
