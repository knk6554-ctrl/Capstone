import unittest

from belt.imu import ScriptedImu
from belt.motors import NullMotor
from belt.turn_tracker import ANGLE_TOLERANCE_DEGREES, TIMEOUT_SECONDS, play_turn


class FakeClock:
    """sleep()이 실제로 기다리는 대신 가상 시계를 그만큼 앞으로 돌린다."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class PlayTurnTests(unittest.TestCase):
    def test_stops_as_soon_as_target_angle_is_reached(self):
        clock = FakeClock()
        motor = NullMotor("RIGHT_WRIST")
        # 90도/초로 돈다고 가정 — 220ms 펄스 한 번당 약 19.8도.
        imu = ScriptedImu([90.0])

        result = play_turn(
            motors=[motor],
            imu=imu,
            intensity=0.9,
            target_angle_degrees=87.0,
            pulse_on_ms=220,
            pulse_off_ms=180,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertTrue(result.completed)
        self.assertGreaterEqual(
            abs(result.rotated_degrees), 87.0 - ANGLE_TOLERANCE_DEGREES
        )
        # 마지막에 반드시 꺼져 있어야 한다.
        self.assertEqual(motor.calls[-1], ("off", 0.0))

    def test_negative_target_uses_absolute_magnitude(self):
        clock = FakeClock()
        motor = NullMotor("LEFT_WRIST")
        imu = ScriptedImu([-90.0])  # 좌회전 방향(음수)으로 계속 도는 상황

        result = play_turn(
            motors=[motor],
            imu=imu,
            intensity=0.9,
            target_angle_degrees=-87.0,
            pulse_on_ms=220,
            pulse_off_ms=180,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertTrue(result.completed)

    def test_gives_up_after_timeout_without_reaching_angle(self):
        clock = FakeClock()
        motor = NullMotor("RIGHT_WRIST")
        imu = ScriptedImu([0.0])  # 전혀 돌지 않는 상황(센서 오류/미동 등)

        result = play_turn(
            motors=[motor],
            imu=imu,
            intensity=0.9,
            target_angle_degrees=87.0,
            pulse_on_ms=220,
            pulse_off_ms=180,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertFalse(result.completed)
        self.assertGreaterEqual(result.elapsed_seconds, TIMEOUT_SECONDS)
        self.assertEqual(motor.calls[-1], ("off", 0.0))

    def test_motor_is_off_between_and_after_pulses(self):
        clock = FakeClock()
        motor = NullMotor("RIGHT_WRIST")
        imu = ScriptedImu([90.0])

        play_turn(
            motors=[motor],
            imu=imu,
            intensity=0.7,
            target_angle_degrees=87.0,
            pulse_on_ms=220,
            pulse_off_ms=180,
            sleep=clock.sleep,
            now=clock.now,
        )

        # on 다음엔 반드시 off가 뒤따른다(계속 켜진 채로 남는 펄스가 없다).
        for i, call in enumerate(motor.calls):
            if call[0] == "on":
                self.assertEqual(motor.calls[i + 1][0], "off")

    def test_no_motors_returns_immediately_without_completing(self):
        clock = FakeClock()
        imu = ScriptedImu([90.0])

        result = play_turn(
            motors=[],
            imu=imu,
            intensity=0.9,
            target_angle_degrees=87.0,
            pulse_on_ms=220,
            pulse_off_ms=180,
            sleep=clock.sleep,
            now=clock.now,
        )

        self.assertFalse(result.completed)
        self.assertEqual(clock.sleeps, [])


if __name__ == "__main__":
    unittest.main()
