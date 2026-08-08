"""Manual route recording: a companion walks the route once and taps a button
at each turn/crosswalk/stairs/destination so the coordinate gets tagged. The
result is written to disk as ``route_<id>.json`` in the shape the belt
(Raspberry Pi) side expects to read back for guidance mode.

This intentionally does not decide *when* to vibrate anything — it only
captures "what kind of point is this, and where". The realtime guidance
decision (distance-to-waypoint, BLE to the wristbands) is out of scope here;
see docs/HARDWARE_PROTOCOL.md and README for the current split of
responsibilities between this web service and the belt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from .models import Coordinate


class WaypointType(str, Enum):
    START = "start"
    LEFT_TURN = "left_turn"
    RIGHT_TURN = "right_turn"
    CROSSWALK = "crosswalk"
    STAIRS = "stairs"
    DESTINATION = "destination"


# Types a person can tap mid-walk. START is added automatically when a
# recording begins; it is not a button the person presses.
TAGGABLE_WAYPOINT_TYPES = frozenset(
    {
        WaypointType.LEFT_TURN,
        WaypointType.RIGHT_TURN,
        WaypointType.CROSSWALK,
        WaypointType.STAIRS,
        WaypointType.DESTINATION,
    }
)


class RecordingNotFoundError(KeyError):
    pass


class RecordingAlreadyFinishedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RecordedWaypoint:
    type: WaypointType
    coordinate: Coordinate
    recorded_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "lat": self.coordinate.latitude,
            "lon": self.coordinate.longitude,
            "recordedAt": self.recorded_at,
        }

    def to_storage_dict(self) -> dict[str, Any]:
        # Flat {type, lat, lon} shape, matching the belt-side route JSON.
        return {
            "type": self.type.value,
            "lat": self.coordinate.latitude,
            "lon": self.coordinate.longitude,
        }


@dataclass(slots=True)
class RecordingSession:
    recording_id: str
    name: str
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    waypoints: list[RecordedWaypoint] = field(default_factory=list)
    finished: bool = False
    saved_route_id: int | None = None

    def add_waypoint(
        self,
        waypoint_type: WaypointType,
        coordinate: Coordinate,
    ) -> RecordedWaypoint:
        if self.finished:
            raise RecordingAlreadyFinishedError(
                "이미 저장이 완료된 기록입니다. 새로 기록을 시작하세요."
            )
        if waypoint_type is WaypointType.DESTINATION and any(
            waypoint.type is WaypointType.DESTINATION for waypoint in self.waypoints
        ):
            raise ValueError("도착 지점은 이미 저장했습니다.")

        waypoint = RecordedWaypoint(
            type=waypoint_type,
            coordinate=coordinate,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.waypoints.append(waypoint)
        return waypoint

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "recordingId": self.recording_id,
            "name": self.name,
            "startedAt": self.started_at,
            "finished": self.finished,
            "savedRouteId": self.saved_route_id,
            "waypoints": [waypoint.to_public_dict() for waypoint in self.waypoints],
        }


_ROUTE_FILE_PATTERN = re.compile(r"route_(\d+)\.json")


class RecordingStore:
    """Holds in-progress recordings in memory and finished ones as JSON files."""

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, RecordingSession] = {}
        self._lock = Lock()
        self._next_route_id = self._infer_next_route_id()

    def _infer_next_route_id(self) -> int:
        max_id = 0
        for path in self._storage_dir.glob("route_*.json"):
            match = _ROUTE_FILE_PATTERN.fullmatch(path.name)
            if match:
                max_id = max(max_id, int(match.group(1)))
        return max_id + 1

    def start(self, name: str, start_coordinate: Coordinate) -> RecordingSession:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("경로 이름을 입력하세요.")
        session = RecordingSession(recording_id=str(uuid4()), name=normalized_name)
        session.add_waypoint(WaypointType.START, start_coordinate)
        with self._lock:
            self._sessions[session.recording_id] = session
        return session

    def get(self, recording_id: str) -> RecordingSession:
        with self._lock:
            try:
                return self._sessions[recording_id]
            except KeyError as exc:
                raise RecordingNotFoundError(recording_id) from exc

    def add_waypoint(
        self,
        recording_id: str,
        waypoint_type: WaypointType,
        coordinate: Coordinate,
    ) -> RecordedWaypoint:
        if waypoint_type not in TAGGABLE_WAYPOINT_TYPES:
            raise ValueError(
                "좌회전/우회전/횡단보도/계단/도착 지점만 직접 태깅할 수 있습니다."
            )
        session = self.get(recording_id)
        return session.add_waypoint(waypoint_type, coordinate)

    def finish(self, recording_id: str) -> dict[str, Any]:
        session = self.get(recording_id)
        if session.finished:
            raise RecordingAlreadyFinishedError("이미 저장이 완료된 기록입니다.")
        if len(session.waypoints) < 2:
            raise ValueError(
                "최소 한 지점 이상 태깅한 뒤 도착 지점을 저장하세요."
            )
        if session.waypoints[-1].type is not WaypointType.DESTINATION:
            raise ValueError(
                "마지막으로 저장된 지점이 '도착 지점 저장'이어야 경로를 저장할 수 있습니다."
            )

        with self._lock:
            route_id = self._next_route_id
            self._next_route_id += 1
            session.finished = True
            session.saved_route_id = route_id

        payload = {
            "route_id": route_id,
            "name": session.name,
            "waypoints": [
                waypoint.to_storage_dict() for waypoint in session.waypoints
            ],
        }
        file_path = self._storage_dir / f"route_{route_id}.json"
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {**payload, "fileName": file_path.name}

    def list_saved(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in sorted(self._storage_dir.glob("route_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            results.append(
                {
                    "routeId": data.get("route_id"),
                    "name": data.get("name", ""),
                    "waypointCount": len(data.get("waypoints", [])),
                    "fileName": path.name,
                }
            )
        return results
