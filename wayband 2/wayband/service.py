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
