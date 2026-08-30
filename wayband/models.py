"""Core domain models kept independent from FastAPI and hardware transports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Maneuver(str, Enum):
    START = "START"
    STRAIGHT = "STRAIGHT"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    UTURN = "UTURN"
    CROSSWALK = "CROSSWALK"
    STAIRS = "STAIRS"
    ARRIVE = "ARRIVE"
    OTHER = "OTHER"


# 시각장애인 보행에서 특히 주의해야 하는 구간을 안내 문구에서 찾아내기 위한 키워드.
# 계단뿐 아니라 계단이 포함되기 쉬운 육교·지하보도도 함께 본다.
STAIR_KEYWORDS = ("계단", "층계", "육교", "지하보도", "지하도")
CROSSWALK_KEYWORDS = ("횡단보도", "건널목")


@dataclass(frozen=True, slots=True)
class Coordinate:
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if not -180 <= self.longitude <= 180:
            raise ValueError("경도는 -180~180 범위여야 합니다.")
        if not -90 <= self.latitude <= 90:
            raise ValueError("위도는 -90~90 범위여야 합니다.")

    def to_public_dict(self) -> dict[str, float]:
        return {"longitude": self.longitude, "latitude": self.latitude}


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    coordinate: Coordinate
    place_id: str = ""
    address: str = ""
    road_address: str = ""
    phone: str = ""
    place_url: str = ""

    @classmethod
    def from_kakao_document(cls, document: dict[str, Any]) -> "Place":
        try:
            return cls(
                name=str(document["place_name"]),
                coordinate=Coordinate(
                    longitude=float(document["x"]),
                    latitude=float(document["y"]),
                ),
                place_id=str(document.get("id", "")),
                address=str(document.get("address_name", "")),
                road_address=str(document.get("road_address_name", "")),
                phone=str(document.get("phone", "")),
                place_url=str(document.get("place_url", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("카카오 장소 응답 형식이 올바르지 않습니다.") from exc

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.place_id,
            "name": self.name,
            "address": self.address,
            "roadAddress": self.road_address,
            "phone": self.phone,
            "placeUrl": self.place_url,
            "coordinate": self.coordinate.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class RouteStep:
    index: int
    guidance: str
    distance_meters: int
    duration_seconds: int
    location: Coordinate
    path: tuple[Coordinate, ...]
    maneuver: Maneuver

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "guidance": self.guidance,
            "distanceMeters": self.distance_meters,
            "durationSeconds": self.duration_seconds,
            "location": self.location.to_public_dict(),
            "path": [point.to_public_dict() for point in self.path],
            "maneuver": self.maneuver.value,
        }


@dataclass(frozen=True, slots=True)
class RoutePlan:
    route_id: str
    start: Place
    destination: Place
    total_distance_meters: int
    total_time_seconds: int
    landing_url: str
    route_mode: str
    steps: tuple[RouteStep, ...]
    path: tuple[Coordinate, ...]

    def hazard_counts(self) -> dict[str, int]:
        """경로 안내 문구에서 계단·횡단보도 구간 수를 센다.

        방향 분류(maneuver)가 회전으로 잡힌 단계에도 '계단' 문구가 섞일 수 있어
        분류 결과가 아니라 원문 guidance를 직접 훑는다.
        """

        stairs = 0
        crosswalks = 0
        for step in self.steps:
            text = step.guidance
            if any(keyword in text for keyword in STAIR_KEYWORDS):
                stairs += 1
            if any(keyword in text for keyword in CROSSWALK_KEYWORDS):
                crosswalks += 1
        return {"stairs": stairs, "crosswalks": crosswalks}

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "routeId": self.route_id,
            "start": self.start.to_public_dict(),
            "destination": self.destination.to_public_dict(),
            "totalDistanceMeters": self.total_distance_meters,
            "totalTimeSeconds": self.total_time_seconds,
            "landingUrl": self.landing_url,
            "routeMode": self.route_mode,
            "hazards": self.hazard_counts(),
            "steps": [step.to_public_dict() for step in self.steps],
            "path": [point.to_public_dict() for point in self.path],
        }
