"""웹 "데이터" 탭용 센서 대시보드 스냅샷 저장소.

벨트(라즈베리파이)가 이미 완성된 모양으로 계산해 보내는 값을 그대로 저장했다가
웹이 폴링해 가져가게 한다 — 서버는 판정 로직을 다시 구현하지 않고 중계만 한다
(장애물 판정은 벨트가 로컬로 한다는 프로젝트 원칙과 일치). 기록은 "가장 최근 값
하나"만 있으면 되므로 hardware/real/sensor_dashboard.py의 SharedState와 같은
락 기반 단일 슬롯 패턴을 그대로 따른다.
"""

from __future__ import annotations

from threading import Lock
from typing import Any


class DashboardSnapshotStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] | None = None
        self._lock = Lock()

    def set(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._payload = payload

    def get(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._payload) if self._payload is not None else None
