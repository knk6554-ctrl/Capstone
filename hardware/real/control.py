from __future__ import annotations

import asyncio
import math
import statistics
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

HARDWARE_ROOT = Path(__file__).resolve().parents[1]
if str(HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(HARDWARE_ROOT))

from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern


class CommandKind(str, Enum):
    TURN = "TURN"
    CROSSWALK = "CROSSWALK"
    ARRIVED = "ARRIVED"


@dataclass(frozen=True, slots=True)
class NavigationCommand:
    kind: CommandKind
    angle_degrees: float | None = None
    message: str = ""


CROSSWALK_PATTERN = PulsePattern(Side.BOTH, (500, 500), (300,), 190)
ARRIVED_PATTERN = PulsePattern(Side.BOTH, (800, 800), (400,), 190)
FRONT_WARNING_PATTERN = PulsePattern(Side.BOTH, (200, 200), (150,), 230)
STRAIGHT_PATTERN = PulsePattern(Side.BOTH, (200,), intensity=150)
ROTATION_FAILED_PATTERN = PulsePattern(Side.BOTH, (150, 150), (100,), 255)
STOP_PATTERN = PulsePattern(Side.BOTH, ())


def _valid(value: int | None) -> bool:
    return value is not None and 0 < value <= 4000


def _column_distances(front: list[int | None]) -> list[int | None]:
    if len(front) != 64:
        raise ValueError("전방 VL53L5CX 프레임은 64셀이어야 합니다.")
    result: list[int | None] = []
    for column in range(8):
        values = [front[row * 8 + column] for row in range(2, 7)]
        valid_values = [value for value in values if _valid(value)]
        result.append(round(statistics.median(valid_values)) if valid_values else None)
    return result


def front_is_blocked(front: list[int | None], limit_mm: int = 1000) -> bool:
    distances = _column_distances(front)
    run = 0
    for value in distances:
        run = run + 1 if _valid(value) and value <= limit_mm else 0
        if run >= 2:
            return True
    return False


def plan_avoidance_angle(
    front: list[int | None],
    left_mm: int | None,
    right_mm: int | None,
    *,
    horizontal_fov_degrees: float = 60.0,
    obstacle_mm: int = 1000,
    clear_mm: int = 1200,
    side_clear_mm: int = 650,
    minimum_corridor_width_mm: int = 600,
) -> float | None:
    """Choose the nearest safe 8x8 corridor; negative=left, positive=right."""

    distances = _column_distances(front)
    cell_angle = horizontal_fov_degrees / 8.0
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for index, distance in enumerate(distances + [None]):
        safe = index < 8 and _valid(distance) and distance >= clear_mm
        if safe and start is None:
            start = index
        elif not safe and start is not None:
            groups.append((start, index - 1))
            start = None

    obstacle_columns = [i for i, value in enumerate(distances) if _valid(value) and value <= obstacle_mm]
    if not obstacle_columns:
        return 0.0
    obstacle_center = statistics.mean(obstacle_columns)
    candidates: list[tuple[float, float]] = []
    for first, last in groups:
        center_column = (first + last) / 2.0
        center_angle = (center_column - 3.5) * cell_angle
        depth = min(distances[first:last + 1])
        angular_width = math.radians((last - first + 1) * cell_angle)
        corridor_width = 2.0 * depth * math.tan(angular_width / 2.0)
        if corridor_width < minimum_corridor_width_mm:
            continue
        if center_angle < 0 and (not _valid(left_mm) or left_mm < side_clear_mm):
            continue
        if center_angle > 0 and (not _valid(right_mm) or right_mm < side_clear_mm):
            continue
        # Prefer the side away from the obstacle, then the smallest deviation.
        away = (center_column - obstacle_center) * (1 if obstacle_center < 3.5 else -1)
        score = abs(center_angle) - (20.0 if away > 0 else 0.0)
        candidates.append((score, center_angle))

    if not candidates:
        return None
    angle = min(candidates)[1]
    if abs(angle) < 10.0:
        angle = math.copysign(10.0, angle or (1.0 if obstacle_center < 3.5 else -1.0))
    return round(max(-30.0, min(30.0, angle)), 1)


class RotationController:
    def __init__(self, wrists, imu, *, tolerance_degrees: float = 4.0, timeout_seconds: float = 10.0, simulate: bool = False):
        self.wrists = wrists
        self.imu = imu
        self.tolerance = tolerance_degrees
        self.timeout = min(timeout_seconds, 10.0)
        self.simulate = simulate

    async def rotate(self, target_degrees: float) -> bool:
        if not -180.0 <= target_degrees <= 180.0 or abs(target_degrees) < 1.0:
            return True
        side = Side.LEFT if target_degrees < 0 else Side.RIGHT
        self.imu.reset()
        await self.wrists.send(PulsePattern(side, (round(self.timeout * 1000),), intensity=220))
        if self.simulate:
            await asyncio.sleep(0.05)
            await self.wrists.stop()
            return True

        entered_at: float | None = None
        started = time.monotonic()
        try:
            while time.monotonic() - started < self.timeout:
                angle, _rate = self.imu.update()
                if abs(target_degrees - angle) <= self.tolerance:
                    entered_at = entered_at or time.monotonic()
                    if time.monotonic() - entered_at >= 0.15:
                        return True
                else:
                    entered_at = None
                if target_degrees > 0 and angle >= target_degrees:
                    return True
                if target_degrees < 0 and angle <= target_degrees:
                    return True
                await asyncio.sleep(0.01)
            return False
        finally:
            await self.wrists.stop()
