from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

HARDWARE = Path(__file__).resolve().parents[1] / "hardware"
REAL = HARDWARE / "real"
for path in (str(HARDWARE), str(REAL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from demo_common import virtual_front_blocked, virtual_front_from_down
from demo_obstacle_auto import choose_avoidance
from wayband_hw.drivers.ble_wrist import BleWristController


class VirtualFrontTests(unittest.TestCase):
    def test_down_upper_half_becomes_virtual_front_lower_half(self):
        down = list(range(1, 65))
        front = virtual_front_from_down(down)
        self.assertEqual(front[:32], [None] * 32)
        self.assertEqual(front[32:], down[:32])

    def test_virtual_front_requires_several_close_cells(self):
        self.assertTrue(virtual_front_blocked([None] * 32 + [500] * 32, 1000))
        self.assertFalse(virtual_front_blocked([None] * 32 + [1500] * 32, 1000))


class BleCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_with_no_connected_wrists_does_not_scan(self):
        controller = BleWristController(simulate=False)
        await asyncio.wait_for(controller.stop(), timeout=0.2)


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
