"""Server-side ToF telemetry evaluator for prototype integration."""

from __future__ import annotations

from enum import Enum
from threading import Lock
from typing import Any

from .haptics import HapticCommand, HapticPattern, HapticTarget


class SensorZone(str, Enum):
    FRONT_LEFT = "FRONT_LEFT"
    FRONT_RIGHT = "FRONT_RIGHT"
    LEFT_SIDE = "LEFT_SIDE"
    RIGHT_SIDE = "RIGHT_SIDE"


class HazardLevel(str, Enum):
    CLEAR = "CLEAR"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    INVALID = "INVALID"


ZONE_TARGETS = {
    SensorZone.FRONT_LEFT: HapticTarget.BELT_FRONT_LEFT,
    SensorZone.FRONT_RIGHT: HapticTarget.BELT_FRONT_RIGHT,
    SensorZone.LEFT_SIDE: HapticTarget.BELT_LEFT_SIDE,
    SensorZone.RIGHT_SIDE: HapticTarget.BELT_RIGHT_SIDE,
}


class HazardDetector:
    def __init__(self, *, warning_mm: int, critical_mm: int, clear_mm: int) -> None:
        if not 0 < critical_mm < warning_mm < clear_mm:
            raise ValueError("ToF 기준은 0 < critical < warning < clear 순서여야 합니다.")
        self.warning_mm = warning_mm
        self.critical_mm = critical_mm
        self.clear_mm = clear_mm
        self._levels: dict[tuple[str, SensorZone], HazardLevel] = {}
        self._lock = Lock()

    def _classify(
        self,
        reading_mm: int,
        previous: HazardLevel,
    ) -> HazardLevel:
        if reading_mm <= 0 or reading_mm > 4000:
            return HazardLevel.INVALID
        if reading_mm <= self.critical_mm:
            return HazardLevel.CRITICAL
        if reading_mm <= self.warning_mm:
            return HazardLevel.WARNING
        if previous in {HazardLevel.WARNING, HazardLevel.CRITICAL}:
            return HazardLevel.CLEAR if reading_mm >= self.clear_mm else previous
        return HazardLevel.CLEAR

    def update(
        self,
        gateway_id: str,
        readings_mm: dict[SensorZone, int],
    ) -> dict[str, Any]:
        commands: list[HapticCommand] = []
        statuses: dict[str, dict[str, Any]] = {}
        with self._lock:
            for zone, reading_mm in readings_mm.items():
                key = (gateway_id, zone)
                previous = self._levels.get(key, HazardLevel.CLEAR)
                current = self._classify(reading_mm, previous)
                self._levels[key] = current
                statuses[zone.value] = {
                    "distanceMm": reading_mm,
                    "level": current.value,
                }

                if current == previous or current in {
                    HazardLevel.CLEAR,
                    HazardLevel.INVALID,
                }:
                    continue
                critical = current is HazardLevel.CRITICAL
                commands.append(
                    HapticCommand(
                        target=ZONE_TARGETS[zone],
                        pattern=(
                            HapticPattern.OBSTACLE_CRITICAL
                            if critical
                            else HapticPattern.OBSTACLE_WARNING
                        ),
                        source="TOF",
                        message=f"{zone.value} 방향 장애물 {reading_mm}mm",
                        intensity=1.0 if critical else 0.7,
                        pulse_count=5 if critical else 2,
                        pulse_on_ms=180 if critical else 300,
                        pulse_off_ms=100 if critical else 220,
                    )
                )

        return {
            "gatewayId": gateway_id,
            "sensors": statuses,
            "commands": [command.to_public_dict() for command in commands],
            "_commandObjects": commands,
        }
