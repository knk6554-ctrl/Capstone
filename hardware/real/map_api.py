from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from control import CommandKind, NavigationCommand

DEFAULT_STATE_PATH = Path(__file__).resolve().parent / "state.json"


def _load_state(state_path: Path) -> tuple[int, str | None]:
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        return int(raw.get("lastSequence", 0)), raw.get("serverInstanceId")
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return 0, None


def _save_state(state_path: Path, sequence: int, server_instance_id: str | None) -> None:
    # 저장 실패(읽기 전용 경로·권한 문제 등)는 다음 순번을 기억 못 할 뿐이지, 지금
    # 받은 지도 명령을 처리하지 못할 이유는 아니다 — 그래서 예외를 삼키고 경고만 남긴다.
    try:
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps({"lastSequence": sequence, "serverInstanceId": server_instance_id}),
            encoding="utf-8",
        )
        tmp_path.replace(state_path)
    except OSError as exc:
        print(f"명령 순번 저장 실패(계속 진행합니다): {exc}")


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
        self.sequence, self.server_instance_id = _load_state(self.state_path)

    def _request(self, after_sequence: int) -> dict:
        query = urlencode({"after_sequence": after_sequence, "limit": 20})
        with urlopen(f"{self.server_url}/api/haptics?{query}", timeout=1) as response:
            return json.loads(response.read().decode("utf-8"))

    def _websocket_url(self) -> str:
        parsed = urlsplit(self.server_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        query = urlencode({"after_sequence": self.sequence})
        return urlunsplit((scheme, parsed.netloc, "/api/haptics/ws", query, ""))

    def _consume(self, payload: dict) -> tuple[list[NavigationCommand], bool]:
        new_instance_id = payload.get("serverInstanceId")
        restarted = (
            self.server_instance_id is not None
            and new_instance_id is not None
            and new_instance_id != self.server_instance_id
        )
        if restarted:
            self.sequence = 0
            self.server_instance_id = new_instance_id
            _save_state(self.state_path, self.sequence, self.server_instance_id)
            return [], True
        if new_instance_id is not None and new_instance_id != self.server_instance_id:
            self.server_instance_id = new_instance_id
            _save_state(self.state_path, self.sequence, self.server_instance_id)

        result: list[NavigationCommand] = []
        priority = {"STAIRS": 0, "CROSSWALK": 1, "TURN_NOW": 2, "ARRIVED": 3}
        commands = sorted(
            payload.get("commands", []),
            key=lambda item: (priority.get(item.get("pattern"), 9), int(item["sequence"])),
        )
        for command in commands:
            self.sequence = max(self.sequence, int(command["sequence"]))
            _save_state(self.state_path, self.sequence, self.server_instance_id)
            if command.get("source") != "NAVIGATION" or _is_stale(command, self.max_age_seconds):
                continue
            created_at = command.get("createdAt", "")
            latency_ms = None
            try:
                created = datetime.fromisoformat(created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                latency_ms = max(0, round((datetime.now(timezone.utc) - created).total_seconds() * 1000))
            except (TypeError, ValueError):
                pass
            common = {
                "message": command.get("message", ""),
                "sequence": int(command["sequence"]),
                "created_at": created_at,
                "latency_ms": latency_ms,
            }
            pattern = command.get("pattern")
            if pattern == "TURN_NOW":
                angle = command.get("targetAngleDegrees")
                if angle is None:
                    angle = -90.0 if command.get("target") == "LEFT_WRIST" else 90.0
                result.append(NavigationCommand(CommandKind.TURN, float(angle), **common))
            elif pattern == "CROSSWALK":
                result.append(NavigationCommand(CommandKind.CROSSWALK, **common))
            elif pattern == "STAIRS":
                result.append(NavigationCommand(CommandKind.STAIRS, **common))
            elif pattern == "ARRIVED":
                result.append(NavigationCommand(CommandKind.ARRIVED, **common))
        return result, False

    def poll(self) -> list[NavigationCommand]:
        payload = self._request(self.sequence)

        # 서버(Render 등)가 재시작되면 진동 명령 순번이 메모리에서 사라지고 1부터
        # 다시 시작한다. 우리가 기억하는 순번이 그대로 남아 있으면 after_sequence가
        # 항상 서버의 현재 순번보다 커서 새 명령을 영영 못 받게 된다 — 서버가 매
        # 응답에 실어 보내는 serverInstanceId가 바뀐 걸 보고 이 상황을 감지해서
        # 순번을 0으로 되돌리고 이번 폴링 안에서 바로 다시 받는다.
        new_instance_id = payload.get("serverInstanceId")
        if (
            self.server_instance_id is not None
            and new_instance_id is not None
            and new_instance_id != self.server_instance_id
        ):
            print("서버가 재시작된 것을 감지해 명령 순번을 초기화합니다.")
            self.sequence = 0
            self.server_instance_id = new_instance_id
            _save_state(self.state_path, self.sequence, self.server_instance_id)
            payload = self._request(self.sequence)
        elif new_instance_id is not None and new_instance_id != self.server_instance_id:
            self.server_instance_id = new_instance_id
            _save_state(self.state_path, self.sequence, self.server_instance_id)

        result, _restarted = self._consume(payload)
        return result

    async def stream(self):
        """Yield command batches over WebSocket, falling back to HTTP polling."""
        try:
            import websockets
        except ImportError:
            websockets = None

        while True:
            if websockets is not None:
                try:
                    async with websockets.connect(
                        self._websocket_url(),
                        open_timeout=3,
                        ping_interval=15,
                        ping_timeout=10,
                    ) as socket:
                        async for raw in socket:
                            commands, restarted = self._consume(json.loads(raw))
                            if restarted:
                                break
                            if commands:
                                yield commands
                        continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f"WebSocket 명령 연결 실패 · HTTP 폴링 사용: {exc}")
            try:
                commands = await asyncio.to_thread(self.poll)
                if commands:
                    yield commands
            except Exception:
                pass
            await asyncio.sleep(0.25)

    async def pump(self, queue: asyncio.Queue[NavigationCommand]) -> None:
        async for commands in self.stream():
            for command in commands:
                await queue.put(command)
