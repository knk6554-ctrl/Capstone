"""벨트 게이트웨이 설정값 — 실제 배선·서버 주소가 정해지면 여기만 바꾸면 된다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# BCM 핀 번호 — 모터 드라이버(트랜지스터/모터 드라이버 IC) 입력에 연결한다.
# HapticTarget(wayband/haptics.py)과 이름을 맞췄다. BOTH_WRISTS는 별도 핀이 아니라
# LEFT_WRIST/RIGHT_WRIST 두 핀을 동시에 울리는 조합으로 처리한다(pattern_player.py 참고).
# 실제 배선에 맞춰 이 값만 바꾸면 된다.
DEFAULT_MOTOR_PINS: dict[str, int] = {
    "LEFT_WRIST": 17,
    "RIGHT_WRIST": 27,
    "BELT_FRONT_LEFT": 22,
    "BELT_FRONT_RIGHT": 23,
    "BELT_LEFT_SIDE": 24,
    "BELT_RIGHT_SIDE": 25,
}

DEFAULT_STATE_PATH = Path(__file__).resolve().parent / "state.json"


@dataclass(frozen=True, slots=True)
class Config:
    server_base_url: str
    poll_interval_seconds: float
    request_timeout_seconds: float
    command_max_age_seconds: float
    state_path: Path
    # False면 IMU를 아예 초기화하지 않는다(미배선 상태에서도 기동해야 할 때) — 회전
    # 안내는 항상 고정 펄스(PREPARE_TURN 1회/TURN_NOW 3회)로만 재생된다.
    imu_enabled: bool = True
    motor_pins: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_MOTOR_PINS))

    @classmethod
    def from_environment(cls) -> "Config":
        return cls(
            server_base_url=os.environ.get(
                "WAYBAND_SERVER_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
            poll_interval_seconds=float(
                os.environ.get("WAYBAND_POLL_INTERVAL_SECONDS", "0.5")
            ),
            request_timeout_seconds=float(
                os.environ.get("WAYBAND_REQUEST_TIMEOUT_SECONDS", "3")
            ),
            # 명령 생성 시각이 이보다 오래되면 실행하지 않고 건너뛴다(HARDWARE_PROTOCOL.md 권장 사항).
            command_max_age_seconds=float(
                os.environ.get("WAYBAND_COMMAND_MAX_AGE_SECONDS", "5")
            ),
            state_path=Path(
                os.environ.get("WAYBAND_STATE_PATH", str(DEFAULT_STATE_PATH))
            ),
            imu_enabled=os.environ.get("WAYBAND_IMU_ENABLED", "1").strip()
            not in ("0", "false", "False", ""),
        )
