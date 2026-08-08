import unittest

from wayband.emergency import AlertNotFoundError, EmergencyCenter
from wayband.models import Coordinate


class EmergencyCenterTests(unittest.TestCase):
    def test_trigger_returns_active_alert(self):
        center = EmergencyCenter()

        alert = center.trigger("도와주세요", Coordinate(127.0, 37.0))

        self.assertEqual(alert.message, "도와주세요")
        self.assertFalse(alert.acknowledged)
        current = center.current()
        self.assertIsNotNone(current)
        self.assertEqual(current.alert_id, alert.alert_id)

    def test_blank_message_gets_default_text(self):
        center = EmergencyCenter()

        alert = center.trigger("", None)

        self.assertEqual(alert.message, "위험 버튼이 눌렸습니다.")

    def test_acknowledge_clears_current_alert(self):
        center = EmergencyCenter()
        alert = center.trigger("도와주세요", None)

        center.acknowledge(alert.alert_id)

        self.assertIsNone(center.current())

    def test_acknowledge_unknown_id_raises(self):
        center = EmergencyCenter()
        center.trigger("도와주세요", None)

        with self.assertRaises(AlertNotFoundError):
            center.acknowledge("no-such-id")

    def test_new_trigger_replaces_previous_active_alert(self):
        center = EmergencyCenter()
        first = center.trigger("첫번째", None)
        second = center.trigger("두번째", None)

        current = center.current()

        self.assertEqual(current.alert_id, second.alert_id)
        with self.assertRaises(AlertNotFoundError):
            center.acknowledge(first.alert_id)


if __name__ == "__main__":
    unittest.main()
