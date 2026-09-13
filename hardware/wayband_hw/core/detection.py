from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

from .events import EventKind, WaybandEvent

Grid = list[int | None]


def valid(value: int | None) -> bool:
    return value is not None and 0 < value <= 4000


def roi(grid: Grid, rows: range, columns: range) -> list[int | None]:
    if len(grid) != 64:
        raise ValueError("VL53L5CX frame must contain 64 cells")
    return [grid[row * 8 + column] for row in rows for column in columns]


def median_mm(values: list[int | None]) -> int | None:
    usable = [value for value in values if valid(value)]
    return round(statistics.median(usable)) if usable else None


def adjacent_near(values: list[int | None], threshold_mm: int, required: int = 2) -> bool:
    run = 0
    for value in values:
        run = run + 1 if valid(value) and value <= threshold_mm else 0
        if run >= required:
            return True
    return False


@dataclass(slots=True)
class ConsecutiveGate:
    required: int = 3
    _counts: dict[EventKind, int] = field(default_factory=dict)

    def confirm(self, kind: EventKind, active: bool) -> bool:
        self._counts[kind] = self._counts.get(kind, 0) + 1 if active else 0
        return self._counts[kind] >= self.required


@dataclass(slots=True)
class EnvironmentDetector:
    baseline_down_mm: int
    gate: ConsecutiveGate = field(default_factory=ConsecutiveGate)
    obstacle_mm: int = 1000
    drop_delta_mm: int = 180
    rise_delta_mm: int = 140

    def evaluate(self, front: Grid, down: Grid) -> list[WaybandEvent]:
        events: list[WaybandEvent] = []
        front_center = roi(front, range(2, 7), range(2, 6))
        front_near = adjacent_near(front_center, self.obstacle_mm, 2)
        nearest = min((v for v in front_center if valid(v)), default=None)
        down_front = roi(down, range(4, 8), range(1, 7))
        down_value = median_mm(down_front)
        missing_ground = down_value is None
        stair_down = down_value is not None and down_value >= self.baseline_down_mm + self.drop_delta_mm

        lower = median_mm(roi(front, range(4, 8), range(0, 8)))
        upper = median_mm(roi(front, range(0, 4), range(0, 8)))
        stair_up = (
            lower is not None and upper is not None and lower <= 1200
            and upper - lower >= self.rise_delta_mm
            and down_value is not None and down_value <= self.baseline_down_mm + 100
        )

        if self.gate.confirm(EventKind.DOWN_DANGER, missing_ground):
            events.append(WaybandEvent(EventKind.DOWN_DANGER, "DOWN_TOF", "평지 기준 낙차", down_value))
        if self.gate.confirm(EventKind.STAIR_DOWN, stair_down):
            events.append(WaybandEvent(EventKind.STAIR_DOWN, "DOWN_TOF", "하행 계단 후보", down_value))
        if self.gate.confirm(EventKind.STAIR_UP, stair_up):
            events.append(WaybandEvent(EventKind.STAIR_UP, "FRONT_DOWN_TOF", "상행 계단 후보", lower))
        if self.gate.confirm(EventKind.FRONT_DANGER, front_near and not stair_up):
            events.append(WaybandEvent(EventKind.FRONT_DANGER, "FRONT_TOF", "중앙 ROI 장애물", nearest))
        return events

    def turn_blocked(self, command: EventKind | None, left_mm: int | None, right_mm: int | None, threshold_mm: int = 500) -> WaybandEvent | None:
        if command is EventKind.TURN_LEFT and valid(left_mm) and left_mm <= threshold_mm:
            return WaybandEvent(EventKind.TURN_BLOCKED_LEFT, "LEFT_TOF", "좌회전 방향 장애물", left_mm)
        if command is EventKind.TURN_RIGHT and valid(right_mm) and right_mm <= threshold_mm:
            return WaybandEvent(EventKind.TURN_BLOCKED_RIGHT, "RIGHT_TOF", "우회전 방향 장애물", right_mm)
        return None
