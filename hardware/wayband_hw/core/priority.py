from __future__ import annotations

import time
from dataclasses import dataclass, field

from .events import EventKind, WaybandEvent
from .patterns import PulsePattern, pattern_for


@dataclass(slots=True)
class PriorityManager:
    """Select the safest event and suppress repeated alerts during cooldown."""

    _last_sent: dict[EventKind, float] = field(default_factory=dict)

    def choose(self, events: list[WaybandEvent], now: float | None = None) -> tuple[WaybandEvent, PulsePattern] | None:
        if not events:
            return None
        now = time.monotonic() if now is None else now
        for event in sorted(events, key=lambda item: item.priority, reverse=True):
            pattern = pattern_for(event)
            previous = self._last_sent.get(event.kind, float("-inf"))
            if pattern.repeat_after_ms and (now - previous) * 1000 < pattern.repeat_after_ms:
                continue
            self._last_sent[event.kind] = now
            return event, pattern
        return None

    def reset(self) -> None:
        self._last_sent.clear()

