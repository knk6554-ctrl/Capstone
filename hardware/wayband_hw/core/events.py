from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Side(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BOTH = "BOTH"


class EventKind(str, Enum):
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    GO_STRAIGHT = "GO_STRAIGHT"
    ARRIVED = "ARRIVED"
    UTURN = "UTURN"
    FRONT_DANGER = "FRONT_DANGER"
    DOWN_DANGER = "DOWN_DANGER"
    STAIR_UP = "STAIR_UP"
    STAIR_DOWN = "STAIR_DOWN"
    TURN_BLOCKED_LEFT = "TURN_BLOCKED_LEFT"
    TURN_BLOCKED_RIGHT = "TURN_BLOCKED_RIGHT"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    STOP = "STOP"


class Priority(IntEnum):
    NAVIGATION = 10
    TURN_BLOCKED = 20
    STAIRS = 30
    COLLISION = 40
    DROP = 50
    SYSTEM = 60


EVENT_PRIORITY = {
    EventKind.TURN_LEFT: Priority.NAVIGATION,
    EventKind.TURN_RIGHT: Priority.NAVIGATION,
    EventKind.GO_STRAIGHT: Priority.NAVIGATION,
    EventKind.ARRIVED: Priority.NAVIGATION,
    EventKind.UTURN: Priority.NAVIGATION,
    EventKind.TURN_BLOCKED_LEFT: Priority.TURN_BLOCKED,
    EventKind.TURN_BLOCKED_RIGHT: Priority.TURN_BLOCKED,
    EventKind.STAIR_UP: Priority.STAIRS,
    EventKind.STAIR_DOWN: Priority.STAIRS,
    EventKind.FRONT_DANGER: Priority.COLLISION,
    EventKind.DOWN_DANGER: Priority.DROP,
    EventKind.SYSTEM_ERROR: Priority.SYSTEM,
    EventKind.STOP: Priority.SYSTEM,
}


@dataclass(frozen=True, slots=True)
class WaybandEvent:
    kind: EventKind
    source: str
    detail: str = ""
    distance_mm: int | None = None

    @property
    def priority(self) -> Priority:
        return EVENT_PRIORITY[self.kind]

