"""Transport-neutral vibration commands and an in-memory polling buffer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any
from uuid import uuid4


class HapticTarget(str, Enum):
    LEFT_WRIST = "LEFT_WRIST"
    RIGHT_WRIST = "RIGHT_WRIST"
    BOTH_WRISTS = "BOTH_WRISTS"
    BELT_FRONT_LEFT = "BELT_FRONT_LEFT"
    BELT_FRONT_RIGHT = "BELT_FRONT_RIGHT"
    BELT_LEFT_SIDE = "BELT_LEFT_SIDE"
    BELT_RIGHT_SIDE = "BELT_RIGHT_SIDE"


class HapticPattern(str, Enum):
    PREPARE_TURN = "PREPARE_TURN"
    TURN_NOW = "TURN_NOW"
    UTURN_NOW = "UTURN_NOW"
    ARRIVED = "ARRIVED"
    OFF_ROUTE = "OFF_ROUTE"
    OBSTACLE_WARNING = "OBSTACLE_WARNING"
    OBSTACLE_CRITICAL = "OBSTACLE_CRITICAL"
    CROSSWALK = "CROSSWALK"
    STAIRS = "STAIRS"


@dataclass(frozen=True, slots=True)
class HapticCommand:
    target: HapticTarget
    pattern: HapticPattern
    source: str
    message: str
    intensity: float
    pulse_count: int
    pulse_on_ms: int
    pulse_off_ms: int
    command_id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not 0 < self.intensity <= 1:
            raise ValueError("진동 세기는 0 초과 1 이하이어야 합니다.")
        if self.pulse_count <= 0:
            raise ValueError("진동 횟수는 1회 이상이어야 합니다.")
        if not self.command_id:
            object.__setattr__(self, "command_id", str(uuid4()))
        if not self.created_at:
            object.__setattr__(
                self,
                "created_at",
                datetime.now(timezone.utc).isoformat(),
            )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "commandId": self.command_id,
            "createdAt": self.created_at,
            "target": self.target.value,
            "pattern": self.pattern.value,
            "source": self.source,
            "message": self.message,
            "intensity": self.intensity,
            "pulseCount": self.pulse_count,
            "pulseOnMs": self.pulse_on_ms,
            "pulseOffMs": self.pulse_off_ms,
        }


@dataclass(frozen=True, slots=True)
class QueuedCommand:
    sequence: int
    command: HapticCommand

    def to_public_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, **self.command.to_public_dict()}


class CommandBuffer:
    """Bounded command history suitable for an ESP32 polling prototype."""

    def __init__(self, max_commands: int = 500) -> None:
        self._commands: deque[QueuedCommand] = deque(maxlen=max_commands)
        self._next_sequence = 1
        self._lock = Lock()

    def publish(self, commands: list[HapticCommand]) -> list[QueuedCommand]:
        queued: list[QueuedCommand] = []
        with self._lock:
            for command in commands:
                item = QueuedCommand(self._next_sequence, command)
                self._next_sequence += 1
                self._commands.append(item)
                queued.append(item)
        return queued

    def after(self, sequence: int, limit: int = 100) -> list[QueuedCommand]:
        if sequence < 0:
            raise ValueError("sequence는 0 이상이어야 합니다.")
        if not 1 <= limit <= 100:
            raise ValueError("limit은 1~100 범위여야 합니다.")
        with self._lock:
            return [item for item in self._commands if item.sequence > sequence][
                :limit
            ]
