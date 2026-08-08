import json
import tempfile
import unittest
from pathlib import Path

from wayband.models import Coordinate
from wayband.recording import (
    RecordingAlreadyFinishedError,
    RecordingNotFoundError,
    RecordingStore,
    WaypointType,
)


class RecordingStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage_dir = Path(self._tmp.name)

    def _store(self) -> RecordingStore:
        return RecordingStore(self.storage_dir)

    def test_start_records_a_start_waypoint_automatically(self):
        store = self._store()

        session = store.start("정문에서 공학관", Coordinate(127.0, 37.0))

        self.assertEqual(len(session.waypoints), 1)
        self.assertEqual(session.waypoints[0].type, WaypointType.START)
        self.assertFalse(session.finished)

    def test_blank_name_is_rejected(self):
        store = self._store()

        with self.assertRaises(ValueError):
            store.start("   ", Coordinate(127.0, 37.0))

    def test_tagging_then_finishing_writes_expected_json_shape(self):
        store = self._store()
        session = store.start("정문에서 공학관", Coordinate(127.12345, 37.12345))

        store.add_waypoint(
            session.recording_id, WaypointType.LEFT_TURN, Coordinate(127.1237, 37.1238)
        )
        store.add_waypoint(
            session.recording_id, WaypointType.CROSSWALK, Coordinate(127.1239, 37.124)
        )
        store.add_waypoint(
            session.recording_id,
            WaypointType.DESTINATION,
            Coordinate(127.1241, 37.1242),
        )

        result = store.finish(session.recording_id)

        self.assertEqual(result["route_id"], 1)
        self.assertEqual(result["name"], "정문에서 공학관")
        self.assertEqual(
            [waypoint["type"] for waypoint in result["waypoints"]],
            ["start", "left_turn", "crosswalk", "destination"],
        )

        saved_file = self.storage_dir / "route_1.json"
        self.assertTrue(saved_file.is_file())
        on_disk = json.loads(saved_file.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["waypoints"][1], {"type": "left_turn", "lat": 37.1238, "lon": 127.1237})

    def test_finish_requires_last_waypoint_to_be_destination(self):
        store = self._store()
        session = store.start("경로", Coordinate(127.0, 37.0))
        store.add_waypoint(
            session.recording_id, WaypointType.LEFT_TURN, Coordinate(127.001, 37.001)
        )

        with self.assertRaises(ValueError):
            store.finish(session.recording_id)

    def test_cannot_tag_after_finish(self):
        store = self._store()
        session = store.start("경로", Coordinate(127.0, 37.0))
        store.add_waypoint(
            session.recording_id, WaypointType.DESTINATION, Coordinate(127.001, 37.001)
        )
        store.finish(session.recording_id)

        with self.assertRaises(RecordingAlreadyFinishedError):
            store.add_waypoint(
                session.recording_id, WaypointType.LEFT_TURN, Coordinate(127.002, 37.002)
            )

    def test_destination_can_only_be_saved_once(self):
        store = self._store()
        session = store.start("경로", Coordinate(127.0, 37.0))
        store.add_waypoint(
            session.recording_id, WaypointType.DESTINATION, Coordinate(127.001, 37.001)
        )

        with self.assertRaises(ValueError):
            store.add_waypoint(
                session.recording_id,
                WaypointType.DESTINATION,
                Coordinate(127.002, 37.002),
            )

    def test_unknown_recording_id_raises_not_found(self):
        store = self._store()

        with self.assertRaises(RecordingNotFoundError):
            store.get("no-such-id")

    def test_route_ids_continue_after_restart(self):
        # Simulate a previous run that already produced route_3.json.
        (self.storage_dir / "route_3.json").write_text(
            json.dumps({"route_id": 3, "name": "이전 경로", "waypoints": []}),
            encoding="utf-8",
        )
        store = self._store()
        session = store.start("새 경로", Coordinate(127.0, 37.0))
        store.add_waypoint(
            session.recording_id, WaypointType.DESTINATION, Coordinate(127.001, 37.001)
        )

        result = store.finish(session.recording_id)

        self.assertEqual(result["route_id"], 4)

    def test_list_saved_returns_summaries(self):
        store = self._store()
        session = store.start("경로", Coordinate(127.0, 37.0))
        store.add_waypoint(
            session.recording_id, WaypointType.DESTINATION, Coordinate(127.001, 37.001)
        )
        store.finish(session.recording_id)

        summaries = store.list_saved()

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["name"], "경로")
        self.assertEqual(summaries[0]["waypointCount"], 2)


if __name__ == "__main__":
    unittest.main()
