"""벨트 게이트웨이 진입점 — /api/haptics를 폴링해 새 진동 명령을 모터로 재생한다.

실행(레포 루트에서):

    python3 -m belt.haptic_client

환경변수(모두 선택, 기본값은 config.py 참고):
    WAYBAND_SERVER_URL              예) http://192.168.0.10:8000
    WAYBAND_POLL_INTERVAL_SECONDS
    WAYBAND_REQUEST_TIMEOUT_SECONDS
    WAYBAND_COMMAND_MAX_AGE_SECONDS
    WAYBAND_STATE_PATH
    WAYBAND_IMU_ENABLED             기본 1 — 0/false로 끄면 회전 안내가 항상 고정 펄스로 재생됨
"""

from __future__ import annotations

import json
import logging
import signal
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType

from .config import Config
from .imu import Imu, RealImu
from .motors import GpioMotor, Motor
from .pattern_player import PatternPlayer

LOGGER = logging.getLogger("wayband.belt")


def _fetch_commands(config: Config, after_sequence: int) -> dict:
    url = (
        f"{config.server_base_url}/api/haptics"
        f"?after_sequence={after_sequence}&limit=100"
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(
        request, timeout=config.request_timeout_seconds
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_last_sequence(state_path: Path) -> int:
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        return int(raw["lastSequence"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return 0


def _save_last_sequence(state_path: Path, sequence: int) -> None:
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps({"lastSequence": sequence}), encoding="utf-8")
    tmp_path.replace(state_path)


def _is_stale(command: dict, max_age_seconds: float) -> bool:
    try:
        created_at = datetime.fromisoformat(command["createdAt"])
    except (KeyError, ValueError):
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    return age_seconds > max_age_seconds


class BeltGateway:
    def __init__(
        self,
        config: Config,
        motors: dict[str, Motor],
        imu: Imu | None = None,
    ) -> None:
        self._config = config
        self._motors = motors
        self._player = PatternPlayer(motors, imu=imu)
        self._last_sequence = _load_last_sequence(config.state_path)
        self._running = True

    def stop(self, _signum: int = 0, _frame: FrameType | None = None) -> None:
        self._running = False

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        LOGGER.info(
            "벨트 게이트웨이 시작 — %s (after_sequence=%s)",
            self._config.server_base_url,
            self._last_sequence,
        )
        try:
            while self._running:
                self._poll_once()
                time.sleep(self._config.poll_interval_seconds)
        finally:
            for motor in self._motors.values():
                motor.off()
            LOGGER.info("모든 모터를 끄고 종료합니다.")

    def _poll_once(self) -> None:
        try:
            payload = _fetch_commands(self._config, self._last_sequence)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            LOGGER.warning("서버 폴링 실패, 다음 주기에 재시도합니다: %s", exc)
            return

        for command in payload.get("commands", []):
            sequence = command.get("sequence", self._last_sequence)
            if sequence <= self._last_sequence:
                continue

            if _is_stale(command, self._config.command_max_age_seconds):
                LOGGER.info(
                    "오래된 명령을 건너뜁니다: seq=%s pattern=%s",
                    sequence,
                    command.get("pattern"),
                )
            else:
                try:
                    self._play(command, sequence)
                except (KeyError, ValueError) as exc:
                    LOGGER.warning(
                        "명령 실행 실패(형식 오류로 건너뜀): seq=%s (%s)", sequence, exc
                    )

            self._last_sequence = sequence
            _save_last_sequence(self._config.state_path, self._last_sequence)

            if not self._running:
                break

    def _play(self, command: dict, sequence: int) -> None:
        if self._player.can_play_turn(command):
            result = self._player.play_turn_command(command)
            if result.completed:
                LOGGER.info(
                    "회전 완료 확인: seq=%s 목표=%.1f도 실제=%.1f도 (%.1fs)",
                    sequence,
                    command["targetAngleDegrees"],
                    result.rotated_degrees,
                    result.elapsed_seconds,
                )
            else:
                LOGGER.warning(
                    "회전 완료를 확인하지 못해 타임아웃으로 진동을 멈췄습니다: "
                    "seq=%s 목표=%.1f도 실제=%.1f도 (%.1fs) — 다음 안내로 넘어갑니다.",
                    sequence,
                    command["targetAngleDegrees"],
                    result.rotated_degrees,
                    result.elapsed_seconds,
                )
            return
        self._player.play(command)


def build_motors(config: Config) -> dict[str, Motor]:
    return {name: GpioMotor(pin) for name, pin in config.motor_pins.items()}


def build_imu(config: Config) -> Imu | None:
    if not config.imu_enabled:
        return None
    try:
        return RealImu()
    except Exception as exc:  # 어떤 이유로든 IMU가 없으면 고정 펄스 패턴으로 폴백한다
        LOGGER.warning(
            "IMU를 초기화하지 못했습니다 — 회전 안내가 고정 펄스 패턴으로 대체됩니다: %s",
            exc,
        )
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    config = Config.from_environment()
    motors = build_motors(config)
    imu = build_imu(config)
    BeltGateway(config, motors, imu).run()


if __name__ == "__main__":
    main()
