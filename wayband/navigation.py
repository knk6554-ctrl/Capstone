"""GPS-driven turn timing with one-shot haptic events and off-route detection."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, radians, sin, sqrt
from typing import Any

from .haptics import HapticCommand, HapticPattern, HapticTarget
from .models import Coordinate, Maneuver, RoutePlan


EARTH_RADIUS_METERS = 6_371_000.0


def haversine_meters(first: Coordinate, second: Coordinate) -> float:
    latitude_delta = radians(second.latitude - first.latitude)
    longitude_delta = radians(second.longitude - first.longitude)
    latitude_1 = radians(first.latitude)
    latitude_2 = radians(second.latitude)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude_1) * cos(latitude_2) * sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * atan2(
        sqrt(value), sqrt(max(0.0, 1 - value))
    )


def _local_xy(point: Coordinate, origin: Coordinate) -> tuple[float, float]:
    x = (
        radians(point.longitude - origin.longitude)
        * EARTH_RADIUS_METERS
        * cos(radians(origin.latitude))
    )
    y = radians(point.latitude - origin.latitude) * EARTH_RADIUS_METERS
    return x, y


def distance_to_polyline_meters(
    location: Coordinate,
    path: tuple[Coordinate, ...],
) -> float:
    distance, _progress = project_onto_polyline_meters(location, path)
    return distance


def project_onto_polyline_meters(
    location: Coordinate,
    path: tuple[Coordinate, ...],
) -> tuple[float, float]:
    """Return distance from the path and distance progressed along the path."""

    if not path:
        return float("inf"), 0.0
    if len(path) == 1:
        return haversine_meters(location, path[0]), 0.0

    best = float("inf")
    best_progress = 0.0
    cumulative = 0.0
    for start, end in zip(path, path[1:]):
        ax, ay = _local_xy(start, location)
        bx, by = _local_xy(end, location)
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            projection = 0.0
            distance = hypot(ax, ay)
        else:
            projection = max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
            distance = hypot(ax + projection * dx, ay + projection * dy)
        segment_length = haversine_meters(start, end)
        if distance < best:
            best = distance
            best_progress = cumulative + projection * segment_length
        cumulative += segment_length
    return best, best_progress


@dataclass(frozen=True, slots=True)
class NavigationEvent:
    maneuver: Maneuver
    location: Coordinate
    guidance: str
    step_index: int


# 좌/우/유턴은 25m 준비 진동이 있지만, 횡단보도·계단은 근접 시 한 번만 울린다.
_NO_PREPARE_MANEUVERS = frozenset({Maneuver.CROSSWALK, Maneuver.STAIRS})


def _events_for(route: RoutePlan) -> tuple[NavigationEvent, ...]:
    haptic_maneuvers = {
        Maneuver.LEFT,
        Maneuver.RIGHT,
        Maneuver.UTURN,
        Maneuver.CROSSWALK,
        Maneuver.STAIRS,
    }
    events = [
        NavigationEvent(
            maneuver=step.maneuver,
            location=step.location,
            guidance=step.guidance,
            step_index=step.index,
        )
        for step in route.steps
        if step.maneuver in haptic_maneuvers
    ]
    # Always use the selected destination coordinate for arrival. A final Kakao
    # step can begin before the actual destination even if its text mentions arrival.
    events.append(
        NavigationEvent(
            maneuver=Maneuver.ARRIVE,
            location=route.destination.coordinate,
            guidance=f"{route.destination.name}에 도착했습니다.",
            step_index=len(route.steps),
        )
    )
    return tuple(events)


def _turn_command(event: NavigationEvent, *, prepare: bool) -> HapticCommand:
    if event.maneuver is Maneuver.LEFT:
        target = HapticTarget.LEFT_WRIST
    elif event.maneuver is Maneuver.RIGHT:
        target = HapticTarget.RIGHT_WRIST
    else:
        target = HapticTarget.BOTH_WRISTS

    if event.maneuver is Maneuver.ARRIVE:
        return HapticCommand(
            target=target,
            pattern=HapticPattern.ARRIVED,
            source="NAVIGATION",
            message=event.guidance,
            intensity=0.75,
            pulse_count=2,
            pulse_on_ms=700,
            pulse_off_ms=250,
        )
    if event.maneuver is Maneuver.CROSSWALK:
        return HapticCommand(
            target=HapticTarget.BOTH_WRISTS,
            pattern=HapticPattern.CROSSWALK,
            source="NAVIGATION",
            message=event.guidance or "횡단보도가 있습니다.",
            intensity=0.8,
            pulse_count=2,
            pulse_on_ms=300,
            pulse_off_ms=220,
        )
    if event.maneuver is Maneuver.STAIRS:
        return HapticCommand(
            target=HapticTarget.BOTH_WRISTS,
            pattern=HapticPattern.STAIRS,
            source="NAVIGATION",
            message=event.guidance or "계단이 있습니다. 주의하세요.",
            intensity=0.85,
            pulse_count=3,
            pulse_on_ms=250,
            pulse_off_ms=150,
        )
    if event.maneuver is Maneuver.UTURN and not prepare:
        pattern = HapticPattern.UTURN_NOW
        pulse_count = 4
    else:
        pattern = HapticPattern.PREPARE_TURN if prepare else HapticPattern.TURN_NOW
        pulse_count = 1 if prepare else 3
    return HapticCommand(
        target=target,
        pattern=pattern,
        source="NAVIGATION",
        message=event.guidance,
        intensity=0.55 if prepare else 0.9,
        pulse_count=pulse_count,
        pulse_on_ms=220,
        pulse_off_ms=180,
    )


class NavigationSession:
    def __init__(
        self,
        route: RoutePlan,
        *,
        prepare_distance_meters: float,
        turn_now_distance_meters: float,
        off_route_distance_meters: float,
    ) -> None:
        self.route = route
        self.events = _events_for(route)
        self.prepare_distance_meters = prepare_distance_meters
        self.turn_now_distance_meters = turn_now_distance_meters
        self.off_route_distance_meters = off_route_distance_meters
        self._event_cursor = 0
        self._prepared_event_indices: set[int] = set()
        self._off_route_count = 0
        self._off_route_alerted = False
        self._route_progress_meters = 0.0
        self._event_progress_meters = tuple(
            project_onto_polyline_meters(event.location, route.path)[1]
            for event in self.events
        )

    def update(self, location: Coordinate, accuracy_meters: float | None) -> dict[str, Any]:
        commands: list[HapticCommand] = []
        route_distance, measured_progress = project_onto_polyline_meters(
            location,
            self.route.path,
        )
        self._route_progress_meters = max(
            self._route_progress_meters,
            measured_progress,
        )
        accuracy_allowance = min(max(accuracy_meters or 0.0, 0.0), 30.0)
        off_route_limit = self.off_route_distance_meters + accuracy_allowance

        if route_distance > off_route_limit:
            self._off_route_count += 1
            if self._off_route_count >= 3 and not self._off_route_alerted:
                commands.append(
                    HapticCommand(
                        target=HapticTarget.BOTH_WRISTS,
                        pattern=HapticPattern.OFF_ROUTE,
                        source="NAVIGATION",
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

        while self._event_cursor < len(self.events):
            current_event = self.events[self._event_cursor]
            distance_to_event = haversine_meters(location, current_event.location)
            if distance_to_event <= self.turn_now_distance_meters:
                commands.append(_turn_command(current_event, prepare=False))
                self._event_cursor += 1
                break
            passed_margin = max(12.0, self.turn_now_distance_meters)
            if (
                current_event.maneuver is not Maneuver.ARRIVE
                and self._route_progress_meters
                > self._event_progress_meters[self._event_cursor] + passed_margin
            ):
                # A sparse/noisy GPS update may jump over the action radius. Skip a
                # stale turn instead of blocking every instruction that follows it.
                self._event_cursor += 1
                continue
            if (
                distance_to_event <= self.prepare_distance_meters
                and self._event_cursor not in self._prepared_event_indices
                and current_event.maneuver not in _NO_PREPARE_MANEUVERS
            ):
                commands.append(_turn_command(current_event, prepare=True))
                self._prepared_event_indices.add(self._event_cursor)
            break

        next_event = (
            self.events[self._event_cursor]
            if self._event_cursor < len(self.events)
            else None
        )
        next_distance = (
            haversine_meters(location, next_event.location)
            if next_event is not None
            else None
        )
        return {
            "routeId": self.route.route_id,
            "location": location.to_public_dict(),
            "distanceFromRouteMeters": round(route_distance, 1),
            "offRoute": self._off_route_count >= 3,
            "completed": next_event is None,
            "nextInstruction": (
                {
                    "stepIndex": next_event.step_index,
                    "maneuver": next_event.maneuver.value,
                    "guidance": next_event.guidance,
                    "distanceMeters": round(next_distance or 0.0, 1),
                }
                if next_event is not None
                else None
            ),
            "commands": [command.to_public_dict() for command in commands],
            "_commandObjects": commands,
        }
