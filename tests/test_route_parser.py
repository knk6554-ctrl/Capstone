import unittest

from wayband.models import Coordinate, Maneuver, Place
from wayband.route_parser import classify_guidance, parse_walking_route


class GuidanceTests(unittest.TestCase):
    def test_korean_turn_words(self):
        self.assertEqual(classify_guidance("왼쪽으로 이동"), Maneuver.LEFT)
        self.assertEqual(classify_guidance("오른쪽 횡단보도로 우회전"), Maneuver.RIGHT)
        self.assertEqual(classify_guidance("유턴하세요"), Maneuver.UTURN)
        self.assertEqual(classify_guidance("목적지 도착"), Maneuver.ARRIVE)

    def test_stairs_and_crosswalk(self):
        self.assertEqual(classify_guidance("계단을 이용하여 내려가세요"), Maneuver.STAIRS)
        self.assertEqual(classify_guidance("육교를 건너세요"), Maneuver.STAIRS)
        self.assertEqual(classify_guidance("횡단보도를 건너세요"), Maneuver.CROSSWALK)


class ParserTests(unittest.TestCase):
    def test_parses_official_walking_shape_and_deduplicates_boundary(self):
        start = Place("출발", Coordinate(127.0, 37.0))
        destination = Place("도착", Coordinate(127.002, 37.002))
        payload = {
            "status": "OK",
            "route": {
                "properties": {
                    "totalDistance": 300,
                    "totalTime": 240,
                    "landingUrl": "https://map.kakao.com/example",
                },
                "legs": [
                    {
                        "steps": [
                            {
                                "properties": {
                                    "distance": 100,
                                    "time": 80,
                                    "guidance": "직진",
                                    "x": 127.0,
                                    "y": 37.0,
                                },
                                "path": {
                                    "points": [[127.0, 37.0], [127.001, 37.0]]
                                },
                            },
                            {
                                "properties": {
                                    "distance": 200,
                                    "time": 160,
                                    "guidance": "왼쪽으로 이동",
                                    "x": 127.001,
                                    "y": 37.0,
                                },
                                "path": {
                                    "points": [[127.001, 37.0], [127.002, 37.002]]
                                },
                            },
                        ]
                    }
                ],
            },
        }

        route = parse_walking_route(
            payload,
            route_id="route-1",
            start=start,
            destination=destination,
            route_mode="ACCESSIBLE",
        )

        self.assertEqual(route.total_distance_meters, 300)
        self.assertEqual(route.steps[1].maneuver, Maneuver.LEFT)
        self.assertEqual(len(route.path), 3)


if __name__ == "__main__":
    unittest.main()
