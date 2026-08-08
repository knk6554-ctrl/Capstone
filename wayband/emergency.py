"""Danger-button alerting.

The visually impaired user presses a button (on the belt, or here a
simulator button in the web UI) when something goes wrong. This module just
holds "is there an active, unacknowledged alert right now" -- the caregiver's
browser polls GET /api/emergency and shows a banner while it's open.

This is intentionally the simplest thing that could work today: one active
alert at a time, no accounts, no push notifications. See README for what a
real push/SMS escalation would need on top of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from .models import Coordinate


class AlertNotFoundError(KeyError):
    pass


@dataclass(slots=True)
class EmergencyAlert:
    alert_id: str
    triggered_at: str
    message: str
    location: Coordinate | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "alertId": self.alert_id,
            "triggeredAt": self.triggered_at,
            "message": self.message,
            "location": self.location.to_public_dict() if self.location else None,
            "acknowledged": self.acknowledged,
            "acknowledgedAt": self.acknowledged_at,
        }


class EmergencyCenter:
    """Holds one active alert at a time -- enough for a single hardcoded pair."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active: EmergencyAlert | None = None
        self._history: list[EmergencyAlert] = []

    def trigger(
        self,
        message: str,
        location: Coordinate | None,
    ) -> EmergencyAlert:
        alert = EmergencyAlert(
            alert_id=str(uuid4()),
            triggered_at=datetime.now(timezone.utc).isoformat(),
            message=message.strip() or "위험 버튼이 눌렸습니다.",
            location=location,
        )
        with self._lock:
            self._active = alert
            self._history.append(alert)
        return alert

    def current(self) -> EmergencyAlert | None:
        with self._lock:
            if self._active is not None and not self._active.acknowledged:
                return self._active
            return None

    def acknowledge(self, alert_id: str) -> EmergencyAlert:
        with self._lock:
            if self._active is None or self._active.alert_id != alert_id:
                raise AlertNotFoundError(alert_id)
            self._active.acknowledged = True
            self._active.acknowledged_at = datetime.now(timezone.utc).isoformat()
            return self._active
