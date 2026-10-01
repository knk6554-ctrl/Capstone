from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

HARDWARE = Path(__file__).resolve().parents[1] / "hardware"
REAL = HARDWARE / "real"
for path in (str(HARDWARE), str(REAL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from demo_common import fill_missing_from_history, virtual_front_blocked, virtual_front_from_down
from demo_obstacle_auto import choose_avoidance
from wayband_hw.drivers.serial_wrist import SerialWristController


class VirtualFrontTests(unittest.TestCase):
    def test_down_upper_half_becomes_virtual_front_lower_half(self):
        down = list(range(1, 65))
        front = virtual_front_from_down(down)
        self.assertEqual(front[32:], down[:32])
        self.assertEqual(front[0:8], [value + 600 for value in down[0:8]])
        self.assertEqual(front[8:16], [value + 450 for value in down[8:16]])
        self.assertEqual(front[16:24], [value + 300 for value in down[16:24]])
        self.assertEqual(front[24:32], [value + 150 for value in down[24:32]])

    def test_virtual_front_requires_several_close_cells(self):
        self.assertTrue(virtual_front_blocked([None] * 32 + [500] * 32, 1000))
        self.assertFalse(virtual_front_blocked([None] * 32 + [1500] * 32, 1000))


class SerialWristTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_with_no_connected_wrists_does_not_scan(self):
        controller = SerialWristController(simulate=False)
        await asyncio.wait_for(controller.stop(), timeout=0.2)

    async def test_simulation_connects_both_serial_wrists(self):
        controller = SerialWristController(simulate=True)
        from wayband_hw.core.events import Side

        await controller.connect(Side.BOTH)
        self.assertEqual(controller.status_text(), "L:connected / R:connected")

    async def test_each_side_uses_its_own_serial_command_prefix(self):
        from wayband_hw.core.events import Side
        from wayband_hw.core.patterns import PulsePattern

        controller = SerialWristController(simulate=False)
        with patch.object(SerialWristController, "_write", new=AsyncMock()) as write:
            await controller._play(Side.LEFT, PulsePattern(Side.LEFT, (1,)))
            await controller._play(Side.RIGHT, PulsePattern(Side.RIGHT, (1,)))
        self.assertEqual(write.await_args_list[0].args, (Side.LEFT, "L1"))
        self.assertEqual(write.await_args_list[1].args, (Side.RIGHT, "R1"))


class MissingValueCorrectionTests(unittest.TestCase):
    def test_short_dropout_uses_previous_value(self):
        previous = [100, 200]
        ages = [0, 0]
        corrected, filled = fill_missing_from_history([None, 210], previous, ages, 2)
        self.assertEqual(corrected, [100, 210])
        self.assertEqual(filled, 1)

    def test_stale_previous_value_expires(self):
        previous = [100]
        ages = [2]
        corrected, filled = fill_missing_from_history([None], previous, ages, 2)
        self.assertEqual(corrected, [None])
        self.assertEqual(filled, 0)

    def test_invalid_value_is_treated_as_missing(self):
        previous = [900]
        ages = [0]
        corrected, filled = fill_missing_from_history([5000], previous, ages, 5)
        self.assertEqual(corrected, [900])
        self.assertEqual(filled, 1)


class AutomaticAvoidanceTests(unittest.TestCase):
    def setUp(self):
        self.blocked_front = [None] * 32 + [500] * 32

    def test_chooses_wider_left_side_and_computes_bounded_angle(self):
        angle = choose_avoidance(self.blocked_front, 1500, 700)
        self.assertIsNotNone(angle)
        self.assertLess(angle, 0)
        self.assertGreaterEqual(abs(angle), 10)
        self.assertLessEqual(abs(angle), 30)

    def test_chooses_right_when_left_is_blocked(self):
        self.assertGreater(choose_avoidance(self.blocked_front, 300, 1200), 0)

    def test_stops_when_both_sides_are_blocked(self):
        self.assertIsNone(choose_avoidance(self.blocked_front, 300, 400))

    def test_returns_zero_when_virtual_front_is_clear(self):
        clear = [None] * 32 + [1800] * 32
        self.assertEqual(choose_avoidance(clear, 1000, 1000), 0.0)


if __name__ == "__main__":
    unittest.main()
