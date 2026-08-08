"""Normalize Kakao walking-route responses and classify guidance text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import atan2, cos, degrees, radians, sin
from typing import Any

from .models import Coordinate, Maneuver, Place, RoutePlan, RouteStep


def classify_guidance(guidance: str) -> Maneuver:
    """Classify Kakao's Korean free-text guidance into haptic categories."""

    text = " ".join(guidance.strip().lower().split())
    if any(keyword in text for keyword in ("도착", "목적지")):
        return Maneuver.ARRIVE
    if any(keyword in text for keyword in ("유턴", "u턴", "u-turn")):
        return Maneuver.UTURN
    if any(keyword in text for keyword in ("좌회전", "왼쪽", "좌측")):
        return Maneuver.LEFT
    if any(keyword in text for keyword in ("우회전", "오른쪽", "우측")):
        return Maneuver.RIGHT
    if "횡단보도" in text:
        return Maneuver.CROSSWALK
    if any(keyword in text for keyword in ("직진", "계속 이동", "따라 이동")):
        return Maneuver.STRAIGHT
    if any(keyword in text for keyword in ("출발", "시작")):
        return Maneuver.START
    return Maneuver.OTHER


def _coordinate(value: Sequence[Any]) -> Coordinate:
    if len(value) < 2:
        raise ValueError("경로 좌표에는 경도와 위도가 모두 필요합니다.")
    return Coordinate(longitude=float(value[0]), latitude=float(value[1]))


def _bearing(start: Coordinate, end: Coordinate) -> float:
    lat1 = radians(start.latitude)
    lat2 = radians(end.latitude)
    longitude_delta = radians(end.longitude - start.longitude)
    y = sin(longitude_delta) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(longitude_delta)
    return (degrees(atan2(y, x)) + 360) % 360


def _infer_turn(
    previous_path: tuple[Coordinate, ...],
    current_path: tuple[Coordinate, ...],
) -> Maneuver:
    """Best-effort fallback when the guidance text has no direction keyword."""

    if len(previous_path) < 2 or len(current_path) < 2:
        return Maneuver.OTHER
    incoming = _bearing(previous_path[-2], previous_path[-1])
    outgoing = _bearing(current_path[0], current_path[1])
    delta = (outgoing - incoming + 540) % 360 - 180
    if 35 <= delta <= 145:
        return Maneuver.RIGHT
    if -145 <= delta <= -35:
        return Maneuver.LEFT
    if abs(delta) > 145:
        return Maneuver.UTURN
    return Maneuver.OTHER


def _parse_step(raw_step: Mapping[str, Any], index: int) -> RouteStep:
    properties = raw_step.get("properties")
    raw_path = raw_step.get("path")
    if not isinstance(properties, Mapping) or not isinstance(raw_path, Mapping):
        raise ValueError(f"경로 {index}번 단계의 형식이 올바르지 않습니다.")

    raw_points = raw_path.get("points", [])
    if not isinstance(raw_points, list):
        raise ValueError(f"경로 {index}번 단계의 points가 배열이 아닙니다.")
    points = tuple(
        _coordinate(point)
        for point in raw_points
        if isinstance(point, Sequence) and not isinstance(point, (str, bytes))
    )
    try:
        location = Coordinate(
            longitude=float(properties["x"]),
            latitude=float(properties["y"]),
        )
        guidance = str(properties.get("guidance", "")).strip()
        return RouteStep(
            index=index,
            guidance=guidance,
            distance_meters=int(properties.get("distance", 0)),
            duration_seconds=int(properties.get("time", 0)),
            location=location,
            path=points or (location,),
            maneuver=classify_guidance(guidance),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"경로 {index}번 단계의 속성이 올바르지 않습니다.") from exc


def parse_walking_route(
    payload: Mapping[str, Any],
    *,
    route_id: str,
    start: Place,
    destination: Place,
    route_mode: str,
) -> RoutePlan:
    """Convert Kakao's nested route response to a validated public model."""

    route = payload.get("route")
    if payload.get("status") != "OK" or not isinstance(route, Mapping):
        raise ValueError("성공한 카카오 도보 경로 응답이 아닙니다.")
    properties = route.get("properties")
    legs = route.get("legs")
    if not isinstance(properties, Mapping) or not isinstance(legs, list):
        raise ValueError("경로 응답의 properties 또는 legs 형식이 올바르지 않습니다.")

    raw_steps: list[Mapping[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            continue
        steps = leg.get("steps", [])
        if isinstance(steps, list):
            raw_steps.extend(step for step in steps if isinstance(step, Mapping))

    parsed_steps = [_parse_step(step, index) for index, step in enumerate(raw_steps)]
    normalized_steps: list[RouteStep] = []
    for index, step in enumerate(parsed_steps):
        maneuver = step.maneuver
        if maneuver is Maneuver.OTHER and index > 0:
            maneuver = _infer_turn(parsed_steps[index - 1].path, step.path)
        normalized_steps.append(
            RouteStep(
                index=step.index,
                guidance=step.guidance,
                distance_meters=step.distance_meters,
                duration_seconds=step.duration_seconds,
                location=step.location,
                path=step.path,
                maneuver=maneuver,
            )
        )

    route_path: list[Coordinate] = []
    for step in normalized_steps:
        for point in step.path:
            if not route_path or point != route_path[-1]:
                route_path.append(point)
    if not route_path:
        route_path = [start.coordinate, destination.coordinate]

    try:
        return RoutePlan(
            route_id=route_id,
            start=start,
            destination=destination,
            total_distance_meters=int(properties["totalDistance"]),
            total_time_seconds=int(properties["totalTime"]),
            landing_url=str(properties.get("landingUrl", "")),
            route_mode=route_mode,
            steps=tuple(normalized_steps),
            path=tuple(route_path),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("경로 전체 속성이 올바르지 않습니다.") from exc
