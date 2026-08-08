"""Turn-by-turn guidance over routes built in 경로 기록 모드 (see recording.py).

Unlike NavigationSession (navigation.py), which follows a continuous Kakao
route with per-step maneuvers, this works off a short list of manually
tagged waypoints: start, left_turn, right_turn, crosswalk, stairs,
destination. Each non-start waypoint fires a haptic command once the walker
gets close enough. The sequence of waypoint coordinates also doubles as the
route's polyline for off-route detection, reusing the same projection math
as navigation.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

from .haptics import HapticCommand, HapticPattern, HapticTarget
from .models import Coordinate
from .navigation import haversine_meters, project_onto_polyline_meters
from .recording import RecordingNotFoundError, RecordingStore, WaypointType


_TURN_TYPES = frozenset({WaypointType.LEFT_TURN, WaypointType.RIGHT_TURN})

_TARGETS = {
    WaypointType.LEFT_TURN: HapticTarget.LEFT_WRIST,
    WaypointType.RIGHT_TURN: HapticTarget.RIGHT_WRIST,
    WaypointType.CROSSWALK: HapticTarget.BOTH_WRISTS,
    WaypointType.STAIRS: HapticTarget.BOTH_WRISTS,
    WaypointType.DESTINATION: HapticTarget.BOTH_WRISTS,
}

_LABELS = {
    WaypointType.LEFT_TURN: "좌회전",
    WaypointType.RIGHT_TURN: "우회전",
    WaypointType.CROSSWALK: "횡단보도",
    WaypointType.STAIRS: "계단",
    WaypointType.DESTINATION: "도착 지점",
}


class RecordedRouteNotStartedError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class _Target:
    index: int
    type: WaypointType
    coordinate: Coordinate


def _command_for(target: _Target, *, prepare: bool) -> HapticCommand:
    haptic_target = _TARGETS[target.type]
    label = _LABELS[target.type]

    if target.type is WaypointType.DESTINATION:
        return HapticCommand(
            target=haptic_target,
            pattern=HapticPattern.ARRIVED,
            source="RECORDED_NAVIGATION",
            message=f"{label}에 도착했습니다.",
            intensity=0.75,
            pulse_count=2,
            pulse_on_ms=700,
            pulse_off_ms=250,
        )
    if target.type is WaypointType.CROSSWALK:
        return HapticCommand(
            target=haptic_target,
            pattern=HapticPattern.CROSSWALK,
            source="RECORDED_NAVIGATION",
            message=f"{label}입니다. 신호를 확인하세요.",
            intensity=0.8,
            pulse_count=2,
            pulse_on_ms=300,
            pulse_off_ms=220,
        )
    if target.type is WaypointType.STAIRS:
        return HapticCommand(
            target=haptic_target,
            pattern=HapticPattern.STAIRS,
            source="RECORDED_NAVIGATION",
            message=f"{label}이 있습니다.",
            intensity=0.85,
            pulse_count=3,
            pulse_on_ms=250,
            pulse_off_ms=150,
        )
    # left_turn / right_turn: two-stage prepare -> now, like NavigationSession.
    pattern = HapticPattern.PREPARE_TURN if prepare else HapticPattern.TURN_NOW
    message = f"{label} 준비" if prepare else label
    return HapticCommand(
        target=haptic_target,
        pattern=pattern,
        source="RECORDED_NAVIGATION",
        message=message,
        intensity=0.55 if prepare else 0.9,
        pulse_count=1 if prepare else 3,
        pulse_on_ms=220,
        pulse_off_ms=180,
    )


class RecordedRouteNavigationSession:
    def __init__(
        self,
        route_id: int,
        name: str,
        waypoints: list[dict[str, Any]],
        *,
        prepare_distance_meters: float,
        turn_now_distance_meters: float,
        off_route_distance_meters: float,
    ) -> None:
        self.route_id = route_id
        self.name = name
        self.prepare_distance_meters = prepare_distance_meters
        self.turn_now_distance_meters = turn_now_distance_meters
        self.off_route_distance_meters = off_route_distance_meters

        self.all_waypoints = [
            {
                "type": waypoint["type"],
                "lat": float(waypoint["lat"]),
                "lon": float(waypoint["lon"]),
            }
            for waypoint in waypoints
        ]
        self._path: tuple[Coordinate, ...] = tuple(
            Coordinate(longitude=w["lon"], latitude=w["lat"])
            for w in self.all_waypoints
        )
        self._targets: list[_Target] = [
            _Target(
                index=index,
                type=WaypointType(w["type"]),
                coordinate=Coordinate(longitude=w["lon"], latitude=w["lat"]),
            )
            for index, w in enumerate(self.all_waypoints)
            if WaypointType(w["type"]) is not WaypointType.START
        ]
        self._cursor = 0
        self._prepared: set[int] = set()
        self._off_route_count = 0
        self._off_route_alerted = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "routeId": self.route_id,
            "name": self.name,
            "waypoints": self.all_waypoints,
        }

    def update(
        self,
        location: Coordinate,
        accuracy_meters: float | None,
    ) -> dict[str, Any]:
        commands: list[HapticCommand] = []

        route_distance, _progress = project_onto_polyline_meters(location, self._path)
        accuracy_allowance = min(max(accuracy_meters or 0.0, 0.0), 30.0)
        off_route_limit = self.off_route_distance_meters + accuracy_allowance

        if route_distance > off_route_limit:
            self._off_route_count += 1
            if self._off_route_count >= 3 and not self._off_route_alerted:
                commands.append(
                    HapticCommand(
                        target=HapticTarget.BOTH_WRISTS,
                        pattern=HapticPattern.OFF_ROUTE,
                        source="RECORDED_NAVIGATION",
                        message="경로에서 벗어났습니다. 위치를 다시 확인하세요.",
                        intensity=1.0,
                        pulse_count=5,
                        pulse_on_ms=120,
                        pulse_off_ms=100,
                    )
                )
                self._off_route_alerted = True
        else:
            self._off_route_count = 0
            if route_distance <= self.off_route_distance_meters * 0.6:
                self._off_route_alerted = False

        if self._cursor < len(self._targets):
            current = self._targets[self._cursor]
            distance_to_target = haversine_meters(location, current.coordinate)
            if distance_to_target <= self.turn_now_distance_meters:
                commands.append(_command_for(current, prepare=False))
                self._cursor += 1
            elif (
                current.type in _TURN_TYPES
                and distance_to_target <= self.prepare_distance_meters
                and current.index not in self._prepared
            ):
                commands.append(_command_for(current, prepare=True))
                self._prepared.add(current.index)

        next_target = (
            self._targets[self._cursor] if self._cursor < len(self._targets) else None
        )
        next_distance = (
            haversine_meters(location, next_target.coordinate)
            if next_target is not None
            else None
        )

        return {
            "routeId": self.route_id,
            "location": location.to_public_dict(),
            "distanceFromRouteMeters": round(route_distance, 1),
            "offRoute": self._off_route_count >= 3,
            "completed": next_target is None,
            "nextWaypoint": (
                {
                    "type": next_target.type.value,
                    "label": _LABELS[next_target.type],
                    "distanceMeters": round(next_distance or 0.0, 1),
                }
                if next_target is not None
                else None
            ),
            "commands": [command.to_public_dict() for command in commands],
            "_commandObjects": commands,
        }


class RecordedNavigationService:
    """Owns one active guidance session per recorded route id."""

    def __init__(self, recordings: RecordingStore, settings: Any) -> None:
        self._recordings = recordings
        self._settings = settings
        self._sessions: dict[int, RecordedRouteNavigationSession] = {}
        self._lock = Lock()

    def start(self, route_id: int) -> RecordedRouteNavigationSession:
        data = self._recordings.load_route(route_id)
        session = RecordedRouteNavigationSession(
            route_id=data["route_id"],
            name=data.get("name", ""),
            waypoints=data.get("waypoints", []),
            prepare_distance_meters=self._settings.prepare_distance_meters,
            turn_now_distance_meters=self._settings.turn_now_distance_meters,
            off_route_distance_meters=self._settings.off_route_distance_meters,
        )
        with self._lock:
            self._sessions[route_id] = session
        return session

    def update(
        self,
        route_id: int,
        location: Coordinate,
        accuracy_meters: float | None,
    ) -> dict[str, Any]:
        with self._lock:
            try:
                session = self._sessions[route_id]
            except KeyError as exc:
                raise RecordedRouteNotStartedError(route_id) from exc
        return session.update(location, accuracy_meters)
