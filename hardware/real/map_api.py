from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from control import CommandKind, NavigationCommand

DEFAULT_STATE_PATH = Path(__file__).resolve().parent / "state.json"


def _load_last_sequence(state_path: Path) -> int:
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        return int(raw["lastSequence"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError, OSError):
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


class MapApi:
    def __init__(
        self,
        server_url: str,
        *,
        state_path: Path | str = DEFAULT_STATE_PATH,
        max_age_seconds: float = 5.0,
    ):
        self.server_url = server_url.rstrip("/")
        self.state_path = Path(state_path)
        self.max_age_seconds = max_age_seconds
        # 프로그램이 재시작돼도 서버 버퍼(최대 500개)에 남은 예전 명령을 처음부터
        # 다시 재생하지 않도록, 마지막으로 처리한 순번을 파일에서 이어받는다.
        self.sequence = _load_last_sequence(self.state_path)

    def poll(self) -> list[NavigationCommand]:
        query = urlencode({"after_sequence": self.sequence, "limit": 20})
        with urlopen(f"{self.server_url}/api/haptics?{query}", timeout=2) as response:
            commands = json.loads(response.read().decode("utf-8"))["commands"]

        result: list[NavigationCommand] = []
        for command in commands:
            self.sequence = max(self.sequence, int(command["sequence"]))
            _save_last_sequence(self.state_path, self.sequence)
            if command.get("source") != "NAVIGATION":
                continue
            # 폴링이 한동안 끊겼다 복구된 경우, 이미 지난 회전·횡단보도 안내를
            # 뒤늦게 실행하지 않는다 (순번은 위에서 이미 전진시켰으므로 다시
            # 요청되지도 않는다).
            if _is_stale(command, self.max_age_seconds):
                continue
            pattern = command.get("pattern")
            if pattern == "TURN_NOW":
                angle = command.get("targetAngleDegrees")
                if angle is None:
                    target = command.get("target")
                    angle = -90.0 if target == "LEFT_WRIST" else 90.0
                result.append(NavigationCommand(CommandKind.TURN, float(angle), command.get("message", "")))
            elif pattern == "CROSSWALK":
                result.append(NavigationCommand(CommandKind.CROSSWALK, message=command.get("message", "")))
            elif pattern == "STAIRS":
                result.append(NavigationCommand(CommandKind.STAIRS, message=command.get("message", "")))
            elif pattern == "ARRIVED":
                result.append(NavigationCommand(CommandKind.ARRIVED, message=command.get("message", "")))
        return result
