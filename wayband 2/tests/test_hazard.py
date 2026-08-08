import unittest

from wayband.hazard import HazardDetector, SensorZone


class HazardTests(unittest.TestCase):
    def test_warning_is_not_repeated_until_state_changes(self):
        detector = HazardDetector(warning_mm=1200, critical_mm=600, clear_mm=1500)

        warning = detector.update("belt", {SensorZone.FRONT_LEFT: 900})
        repeated = detector.update("belt", {SensorZone.FRONT_LEFT: 850})
        critical = detector.update("belt", {SensorZone.FRONT_LEFT: 500})

        self.assertEqual(warning["commands"][0]["pattern"], "OBSTACLE_WARNING")
        self.assertEqual(repeated["commands"], [])
        self.assertEqual(critical["commands"][0]["pattern"], "OBSTACLE_CRITICAL")

    def test_hysteresis_keeps_warning_until_clear_threshold(self):
        detector = HazardDetector(warning_mm=1200, critical_mm=600, clear_mm=1500)
        detector.update("belt", {SensorZone.RIGHT_SIDE: 1000})

        middle = detector.update("belt", {SensorZone.RIGHT_SIDE: 1300})
        clear = detector.update("belt", {SensorZone.RIGHT_SIDE: 1600})

        self.assertEqual(middle["sensors"]["RIGHT_SIDE"]["level"], "WARNING")
        self.assertEqual(clear["sensors"]["RIGHT_SIDE"]["level"], "CLEAR")


if __name__ == "__main__":
    unittest.main()
