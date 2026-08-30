"""Application services and in-memory prototype state."""

from __future__ import annotations

from threading import Lock
from typing import cast
from uuid import uuid4

from .config import Settings
from .haptics import CommandBuffer, HapticCommand
from .kakao import KakaoClient
from .models import Coordinate, Place, RoutePlan
from .navigation import NavigationSession
from .route_parser import parse_walking_route


class RouteNotFoundError(KeyError):
    pass


class WaybandService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.kakao = KakaoClient(settings.kakao_rest_api_key)
        self.commands = CommandBuffer()
        self._routes: dict[str, RoutePlan] = {}
        self._sessions: dict[str, NavigationSession] = {}
        self._lock = Lock()

    def search_places(
        self,
        query: str,
        *,
        center: Coordinate | None = None,
    ) -> list[Place]:
        return self.kakao.search_places(query, center=center)

    def create_route(
        self,
        start: Place,
        destination: Place,
        route_mode: str,
    ) -> RoutePlan:
        payload = self.kakao.request_walking_route(
            start,
            destination,
            route_mode=route_mode,
        )
        route_id = str(uuid4())
        route = parse_walking_route(
            payload,
            route_id=route_id,
            start=start,
            destination=destination,
            route_mode=route_mode,
        )
        session = NavigationSession(
            route,
            prepare_distance_meters=self.settings.prepare_distance_meters,
            turn_now_distance_meters=self.settings.turn_now_distance_meters,
            off_route_distance_meters=self.settings.off_route_distance_meters,
        )
        with self._lock:
            self._routes[route_id] = route
            self._sessions[route_id] = session
        return route

    # 사용자가 고른 모드의 "반대편" 경로를 한 번 더 조회해 두 경로를 비교한다.
    # 안전 경로(ACCESSIBLE)는 빠른 경로(SHORTEST)와, 그 외에는 안전 경로와 비교한다.
    _COMPARISON_COUNTERPART = {
        "ACCESSIBLE": "SHORTEST",
        "SHORTEST": "ACCESSIBLE",
        "BROAD_FIRST": "ACCESSIBLE",
    }
    _MODE_LABELS = {
        "ACCESSIBLE": "안전 경로",
        "SHORTEST": "빠른 경로",
        "BROAD_FIRST": "넓은 길 경로",
    }

    def compare_route(
        self,
        primary: RoutePlan,
        start: Place,
        destination: Place,
    ) -> dict[str, object] | None:
        counterpart_mode = self._COMPARISON_COUNTERPART.get(primary.route_mode)
        if counterpart_mode is None or counterpart_mode == primary.route_mode:
            return None
        try:
            payload = self.kakao.request_walking_route(
                start,
                destination,
                route_mode=counterpart_mode,
            )
            other = parse_walking_route(
                payload,
                route_id="comparison",
                start=start,
                destination=destination,
                route_mode=counterpart_mode,
            )
        except Exception:
            # 비교 경로 조회 실패가 기본 경로 응답을 막으면 안 된다.
            return None

        primary_hazards = primary.hazard_counts()
        other_hazards = other.hazard_counts()
        return {
            "mode": counterpart_mode,
            "label": self._MODE_LABELS.get(counterpart_mode, counterpart_mode),
            "primaryLabel": self._MODE_LABELS.get(
                primary.route_mode, primary.route_mode
            ),
            "totalDistanceMeters": other.total_distance_meters,
            "totalTimeSeconds": other.total_time_seconds,
            "hazards": other_hazards,
            # 양수 = 현재(기본) 경로가 더 길다 / 더 오래 걸린다
            "distanceDeltaMeters": primary.total_distance_meters
            - other.total_distance_meters,
            "timeDeltaSeconds": primary.total_time_seconds - other.total_time_seconds,
            # 양수 = 반대편 경로가 계단/횡단보도를 그만큼 더 지난다
            "stairsDelta": other_hazards["stairs"] - primary_hazards["stairs"],
            "crosswalksDelta": other_hazards["crosswalks"]
            - primary_hazards["crosswalks"],
        }

    def route(self, route_id: str) -> RoutePlan:
        with self._lock:
            try:
                return self._routes[route_id]
            except KeyError as exc:
                raise RouteNotFoundError(route_id) from exc

    def update_location(
        self,
        route_id: str,
        location: Coordinate,
        accuracy_meters: float | None,
    ) -> dict[str, object]:
        with self._lock:
            try:
                session = self._sessions[route_id]
            except KeyError as exc:
                raise RouteNotFoundError(route_id) from exc
            result = session.update(location, accuracy_meters)
        command_objects = cast(list[HapticCommand], result.pop("_commandObjects"))
        self.commands.publish(command_objects)
        return result
