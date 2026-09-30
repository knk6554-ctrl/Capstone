from __future__ import annotations

from dataclasses import dataclass

from .events import EventKind, Side, WaybandEvent


@dataclass(frozen=True, slots=True)
class PulsePattern:
    side: Side
    pulses_ms: tuple[int, ...]
    gaps_ms: tuple[int, ...] = ()
    intensity: int = 255
    repeat_after_ms: int = 0

    def __post_init__(self) -> None:
        if self.gaps_ms and len(self.gaps_ms) != len(self.pulses_ms) - 1:
            raise ValueError("gaps_ms must contain one fewer item than pulses_ms")

    def wire_command(self) -> str:
        pulses = ",".join(str(value) for value in self.pulses_ms)
        gaps = ",".join(str(value) for value in self.gaps_ms)
        return f"P|{pulses}|{gaps}|{self.intensity}"


PATTERNS = {
    EventKind.TURN_LEFT: PulsePattern(Side.LEFT, (1000,)),
    EventKind.TURN_RIGHT: PulsePattern(Side.RIGHT, (1000,)),
    EventKind.GO_STRAIGHT: PulsePattern(Side.BOTH, (180,), intensity=150),
    EventKind.ARRIVED: PulsePattern(Side.BOTH, (700, 700), (350,)),
    EventKind.UTURN: PulsePattern(Side.BOTH, (180, 180, 180, 180), (120, 120, 120)),
    EventKind.FRONT_DANGER: PulsePattern(Side.BOTH, (220, 220), (180,), repeat_after_ms=1500),
    EventKind.DOWN_DANGER: PulsePattern(Side.BOTH, (160, 160, 160), (100, 100), repeat_after_ms=1000),
    EventKind.STAIR_UP: PulsePattern(Side.BOTH, (180, 650), (250,), repeat_after_ms=2500),
    EventKind.STAIR_DOWN: PulsePattern(Side.BOTH, (140, 140, 140), (90, 90), repeat_after_ms=1800),
    EventKind.TURN_BLOCKED_LEFT: PulsePattern(Side.LEFT, (100, 100, 100, 100), (70, 70, 70), repeat_after_ms=1000),
    EventKind.TURN_BLOCKED_RIGHT: PulsePattern(Side.RIGHT, (100, 100, 100, 100), (70, 70, 70), repeat_after_ms=1000),
    EventKind.SYSTEM_ERROR: PulsePattern(Side.BOTH, (1000, 1000), (400,), repeat_after_ms=3000),
    EventKind.STOP: PulsePattern(Side.BOTH, ()),
}


def pattern_for(event: WaybandEvent) -> PulsePattern:
    pattern = PATTERNS[event.kind]
    if event.kind is EventKind.FRONT_DANGER and event.distance_mm is not None:
        if event.distance_mm <= 300:
            return PulsePattern(Side.BOTH, (120, 120, 120, 120, 120), (70, 70, 70, 70), 255, 700)
        if event.distance_mm <= 600:
            return PulsePattern(Side.BOTH, pattern.pulses_ms, pattern.gaps_ms, 255, 1200)
        return PulsePattern(Side.BOTH, pattern.pulses_ms, pattern.gaps_ms, 150, 1800)
    return pattern

