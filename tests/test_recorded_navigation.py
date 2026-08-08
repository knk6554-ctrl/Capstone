import tempfile
import unittest
from pathlib import Path

from wayband.models import Coordinate
from wayband.recorded_navigation import (
    RecordedNavigationService,
    RecordedRouteNotStartedError,
)
from wayband.recording import RecordingStore, WaypointType


class _FakeSettings:
    prepare_distance_meters = 25.0
    turn_now_distance_meters = 8.0
    off_route_distance_meters = 35.0


class RecordedNavigationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage_dir = Path(self._tmp.name)
        self.recordings = RecordingStore(self.storage_dir)

        session = self.recordings.start("정문에서 공학관", Coordinate(127.0, 37.0))
        self.recordings.add_waypoint(
            session.recording_id, WaypointType.LEFT_TURN, Coordinate(127.0005, 37.0005)
        )
        self.recordings.add_waypoint(
            session.recording_id, WaypointType.CROSSWALK, Coordinate(127.001, 37.001)
        )
        self.recordings.add_waypoint(
            session.recording_id, WaypointType.DESTINATION, Coordinate(127.0015, 37.0015)
        )
        self.finished = self.recordings.finish(session.recording_id)
        self.route_id = self.finished["route_id"]

        self.service = RecordedNavigationService(self.recordings, _FakeSettings())

    def test_start_returns_all_waypoints_including_start(self):
        session = self.service.start(self.route_id)

        self.assertEqual(len(session.all_waypoints), 4)
        self.assertEqual(session.all_waypoints[0]["type"], "start")

    def test_left_turn_triggers_prepare_then_now(self):
        self.service.start(self.route_id)
        near = Coordinate(127.0005, 37.0003)
        at_turn = Coordinate(127.0005, 37.0005)

        prepare = self.service.update(self.route_id, near, 3)
        turn_now = self.service.update(self.route_id, at_turn, 3)

        self.assertEqual(prepare["commands"][0]["target"], "LEFT_WRIST")
        self.assertEqual(prepare["commands"][0]["pattern"], "PREPARE_TURN")
        self.assertEqual(turn_now["commands"][0]["pattern"], "TURN_NOW")

    def test_crosswalk_and_destination_fire_without_prepare_stage(self):
        self.service.start(self.route_id)
        # Skip past the left turn directly to the crosswalk point.
        self.service.update(self.route_id, Coordinate(127.0005, 37.0005), 3)

        crosswalk = self.service.update(self.route_id, Coordinate(127.001, 37.001), 3)
        self.assertEqual(crosswalk["commands"][0]["pattern"], "CROSSWALK")

        destination = self.service.update(self.route_id, Coordinate(127.0015, 37.0015), 3)
        self.assertEqual(destination["commands"][0]["pattern"], "ARRIVED")
        self.assertTrue(destination["completed"])

    def test_update_without_start_raises(self):
        with self.assertRaises(RecordedRouteNotStartedError):
            self.service.update(self.route_id, Coordinate(127.0, 37.0), 3)


if __name__ == "__main__":
    unittest.main()
