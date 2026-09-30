import asyncio
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
        await controller._play(PulsePattern(Side.LEFT, (100,), intensity=255))

        self.assertEqual(controller.motors[Side.LEFT].calls, [("on", 1.0), ("off", 0.0)])
        self.assertEqual(controller.motors[Side.RIGHT].calls, [])

    async def test_both_side_drives_both_motors(self):
        controller = self._controller()

        await controller._play(PulsePattern(Side.BOTH, (100,), intensity=255))

        self.assertTrue(controller.motors[Side.LEFT].calls)
        self.assertTrue(controller.motors[Side.RIGHT].calls)

    async def test_intensity_is_normalized_from_0_255_to_0_1(self):
        controller = self._controller()

        await controller._play(PulsePattern(Side.RIGHT, (10,), intensity=128))

        on_call = controller.motors[Side.RIGHT].calls[0]
        self.assertEqual(on_call[0], "on")
        self.assertAlmostEqual(on_call[1], 128 / 255, places=4)

    async def test_uneven_pulses_and_gaps_play_in_order(self):
        # 계단 패턴처럼 펄스 길이가 균일하지 않은 경우 — belt/의 균일 on/off 가정과
        # 달리 인덱스별로 그대로 재생돼야 한다.
        controller = self._controller()

        await controller._play(PulsePattern(Side.LEFT, (180, 650), (250,), 200))

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

    # --- send()가 재생이 끝날 때까지 블로킹하지 않는지 (회전 추적의 핵심 전제) ---

    async def test_send_returns_before_a_long_pattern_finishes_playing(self):
        controller = self._controller()
        long_pattern = PulsePattern(Side.LEFT, (5000,), intensity=255)  # 5초짜리 펄스

        # send()가 예전처럼 asyncio.sleep(5)를 직접 기다리는 블로킹 구현이었다면
        # 여기서 타임아웃돼야 한다 — BLE처럼 명령만 걸어두고 바로 반환해야 한다.
        await asyncio.wait_for(controller.send(long_pattern), timeout=0.5)

        await controller.stop()

    async def test_stop_cancels_in_progress_pattern_before_it_completes(self):
        controller = self._controller()
        long_pattern = PulsePattern(Side.LEFT, (5000,), intensity=255)

        await controller.send(long_pattern)
        await asyncio.sleep(0.02)  # 모터가 실제로 켜질 시간을 아주 잠깐 준다

        # 5초를 기다리지 않고, RotationController가 목표각 도달 시 하듯 즉시 끊는다.
        await asyncio.wait_for(controller.stop(), timeout=0.5)

        self.assertEqual(controller.motors[Side.LEFT].calls[-1], ("off", 0.0))
        # on은 한 번만 — 5초짜리 펄스가 반복되거나 끝까지 재생되지 않고 조기에 끊겼다는 뜻.
        on_calls = [call for call in controller.motors[Side.LEFT].calls if call[0] == "on"]
        self.assertEqual(len(on_calls), 1)

    async def test_new_send_replaces_a_still_playing_pattern(self):
        controller = self._controller()
        await controller.send(PulsePattern(Side.LEFT, (5000,), intensity=255))
        await asyncio.sleep(0.02)

        await asyncio.wait_for(
            controller.send(PulsePattern(Side.RIGHT, (10,), intensity=200)), timeout=0.5
        )
        await asyncio.sleep(0.05)

        self.assertEqual(controller.motors[Side.LEFT].calls[-1], ("off", 0.0))
        self.assertIn(("off", 0.0), controller.motors[Side.RIGHT].calls)


if __name__ == "__main__":
    unittest.main()
