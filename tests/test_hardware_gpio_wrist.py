import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARDWARE_ROOT = ROOT / "hardware"
if str(HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(HARDWARE_ROOT))

from wayband_hw.core.events import Side  # noqa: E402
from wayband_hw.core.patterns import PulsePattern  # noqa: E402
from wayband_hw.drivers.gpio_wrist import GpioWristController  # noqa: E402


class GpioWristControllerTests(unittest.IsolatedAsyncioTestCase):
    def _controller(self):
        return GpioWristController(simulate=True)

    async def test_simulate_uses_null_motors_without_gpiozero(self):
        controller = self._controller()

        # gpiozero가 설치돼 있지 않은 개발 PC에서도 여기까지 예외 없이 와야 한다.
        await controller.send(PulsePattern(Side.LEFT, (100,), intensity=255))

        self.assertEqual(controller.motors[Side.LEFT].calls, [("on", 1.0), ("off", 0.0)])
        self.assertEqual(controller.motors[Side.RIGHT].calls, [])

    async def test_both_side_drives_both_motors(self):
        controller = self._controller()

        await controller.send(PulsePattern(Side.BOTH, (100,), intensity=255))

        self.assertTrue(controller.motors[Side.LEFT].calls)
        self.assertTrue(controller.motors[Side.RIGHT].calls)

    async def test_intensity_is_normalized_from_0_255_to_0_1(self):
        controller = self._controller()

        await controller.send(PulsePattern(Side.RIGHT, (10,), intensity=128))

        on_call = controller.motors[Side.RIGHT].calls[0]
        self.assertEqual(on_call[0], "on")
        self.assertAlmostEqual(on_call[1], 128 / 255, places=4)

    async def test_uneven_pulses_and_gaps_play_in_order(self):
        # 계단 패턴처럼 펄스 길이가 균일하지 않은 경우 — belt/의 균일 on/off 가정과
        # 달리 인덱스별로 그대로 재생돼야 한다.
        controller = self._controller()

        await controller.send(PulsePattern(Side.LEFT, (180, 650), (250,), 200))

        self.assertEqual(
            controller.motors[Side.LEFT].calls,
            [("on", 200 / 255), ("off", 0.0), ("on", 200 / 255), ("off", 0.0)],
        )

    async def test_stop_turns_off_both_motors(self):
        controller = self._controller()
        await controller.send(PulsePattern(Side.LEFT, (100,), intensity=255))

        await controller.stop()

        self.assertEqual(controller.motors[Side.LEFT].calls[-1], ("off", 0.0))
        self.assertEqual(controller.motors[Side.RIGHT].calls[-1], ("off", 0.0))


if __name__ == "__main__":
    unittest.main()
