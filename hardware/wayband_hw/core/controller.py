from __future__ import annotations

from dataclasses import dataclass, field

from .detection import EnvironmentDetector, Grid
from .events import EventKind, WaybandEvent
from .patterns import PulsePattern
from .priority import PriorityManager


@dataclass(slots=True)
class Decision:
    event: WaybandEvent
    pattern: PulsePattern


@dataclass(slots=True)
class WaybandController:
    """Fuse a simple map command with one complete four-ToF snapshot."""

    baseline_down_mm: int
    detector: EnvironmentDetector = field(init=False)
    priority: PriorityManager = field(default_factory=PriorityManager)
    map_command: EventKind | None = None

    def __post_init__(self) -> None:
        self.detector = EnvironmentDetector(self.baseline_down_mm)

    def set_map_command(self, command: EventKind | None) -> None:
        allowed = {EventKind.TURN_LEFT, EventKind.TURN_RIGHT, EventKind.GO_STRAIGHT, EventKind.ARRIVED, EventKind.UTURN}
        if command is not None and command not in allowed:
            raise ValueError("map module may only send navigation commands")
        self.map_command = command

    def update(self, front: Grid, down: Grid, left_mm: int | None, right_mm: int | None, now: float | None = None) -> Decision | None:
        events = self.detector.evaluate(front, down)
        blocked = self.detector.turn_blocked(self.map_command, left_mm, right_mm)
        if blocked is not None:
            events.append(blocked)
        if self.map_command is not None:
            events.append(WaybandEvent(self.map_command, "MAP"))
        selected = self.priority.choose(events, now)
        return None if selected is None else Decision(*selected)

    def stop(self) -> None:
        self.map_command = None
        self.priority.reset()

