import unittest

from control import plan_avoidance_angle


def frame(left=1800, right=1800):
    values = [1800] * 64
    for row in range(2, 7):
        for column in range(4):
            values[row * 8 + column] = left
        for column in range(4, 8):
            values[row * 8 + column] = right
    return values


class AvoidancePlannerTests(unittest.TestCase):
    def test_left_obstacle_selects_right(self):
        self.assertGreater(plan_avoidance_angle(frame(650, 1800), 900, 1800), 0)

    def test_right_obstacle_selects_left(self):
        self.assertLess(plan_avoidance_angle(frame(1800, 650), 1800, 900), 0)

    def test_blocked_side_rejects_corridor(self):
        self.assertIsNone(plan_avoidance_angle(frame(650, 1800), 900, 400))

    def test_clear_frame_needs_no_avoidance(self):
        self.assertEqual(plan_avoidance_angle(frame(), 1800, 1800), 0)


if __name__ == "__main__":
    unittest.main()
