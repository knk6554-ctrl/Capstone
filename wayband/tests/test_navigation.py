import unittest

from wayband.models import Coordinate, Maneuver, Place, RoutePlan, RouteStep
from wayband.navigation import NavigationSession


class NavigationTests(unittest.TestCase):
    def setUp(self):
        start = Place("출발", Coordinate(127.0, 37.0))
        destination = Place("도착", Coordinate(127.001, 37.001))
        turn = Coordinate(127.0005, 37.0005)
        self.route = RoutePlan(
            route_id="route-1",
            start=start,
            destination=destination,
            total_distance_meters=200,
            total_time_seconds=180,
            landing_url="",
            route_mode="ACCESSIBLE",
            steps=(
                RouteStep(
                    index=0,
                    guidance="왼쪽으로 이동",
                    distance_meters=100,
                    duration_seconds=90,
                    location=turn,
                    path=(start.coordinate, turn, destination.coordinate),
                    maneuver=Maneuver.LEFT,
                ),
            ),
            path=(start.coordinate, turn, destination.coordinate),
        )

    def test_left_turn_prepare_and_now_are_one_shot(self):
        session = NavigationSession(
            self.route,
            prepare_distance_meters=25,
            turn_now_distance_meters=8,
            off_route_distance_meters=35,
        )
        near = Coordinate(127.0005, 37.0003)
        at_turn = Coordinate(127.0005, 37.0005)

        prepare = session.update(near, 3)
        repeated = session.update(near, 3)
        turn_now = session.update(at_turn, 3)

        self.assertEqual(prepare["commands"][0]["target"], "LEFT_WRIST")
        self.assertEqual(prepare["commands"][0]["pattern"], "PREPARE_TURN")
        self.assertEqual(repeated["commands"], [])
        self.assertEqual(turn_now["commands"][0]["pattern"], "TURN_NOW")

    def test_missed_turn_does_not_block_arrival_instruction(self):
        session = NavigationSession(
            self.route,
            prepare_distance_meters=25,
            turn_now_distance_meters=8,
            off_route_distance_meters=35,
        )

        result = session.update(Coordinate(127.0008, 37.0008), 3)

        self.assertEqual(result["nextInstruction"]["maneuver"], "ARRIVE")


if __name__ == "__main__":
    unittest.main()
