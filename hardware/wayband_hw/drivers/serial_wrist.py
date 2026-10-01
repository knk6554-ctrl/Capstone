from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core.events import Side
from ..core.patterns import PulsePattern

IDENTITY = {Side.LEFT: "WAYBAND_LEFT", Side.RIGHT: "WAYBAND_RIGHT"}
PREFIX = {Side.LEFT: "L", Side.RIGHT: "R"}


@dataclass(slots=True)
class WristStatus:
    connected: bool = False
    battery_percent: int | None = None
    last_response: str = "-"
    last_error: str = ""
    vibrating_until: float = 0.0


@dataclass(slots=True)
class SerialWristController:
    """Control two ESP32 DevKit wrists over independent USB serial ports."""

    simulate: bool = False
    serial_baud: int = 115200
    ports: dict[Side, object] = field(default_factory=dict)
    statuses: dict[Side, WristStatus] = field(
        default_factory=lambda: {Side.LEFT: WristStatus(), Side.RIGHT: WristStatus()}
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _tasks: dict[Side, asyncio.Task] = field(default_factory=dict, init=False, repr=False)

    @staticmethod
    def _configured(side: Side) -> str | None:
        name = "WAYBAND_LEFT_SERIAL" if side is Side.LEFT else "WAYBAND_RIGHT_SERIAL"
        return os.environ.get(name)

    @staticmethod
    def _path_key(path: str) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return path

    @staticmethod
    def _candidates() -> list[str]:
        result, seen = [], set()
        for pattern in ("dev/serial/by-id/*", "dev/serial/by-path/*", "dev/ttyUSB*", "dev/ttyACM*"):
            for path in sorted(Path("/").glob(pattern)):
                try:
                    key = str(path.resolve())
                except OSError:
                    key = str(path)
                if key not in seen:
                    seen.add(key)
                    result.append(str(path))
        return result

    async def _open(self, path: str):
        import serial

        port = await asyncio.to_thread(
            serial.Serial, path, self.serial_baud, timeout=0.15, write_timeout=1
        )
        await asyncio.sleep(0.9)  # Opening USB serial usually resets an ESP32.
        return port

    async def _identify(self, port: object) -> Side | None:
        try:
            await asyncio.to_thread(port.reset_input_buffer)
            await asyncio.to_thread(port.write, b"I\n")
            await asyncio.to_thread(port.flush)
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline:
                text = (await asyncio.to_thread(port.readline)).decode(
                    "utf-8", errors="replace"
                )
                for side in (Side.LEFT, Side.RIGHT):
                    if IDENTITY[side] in text:
                        return side
        except Exception:
            pass
        return None

    async def _drop(self, side: Side) -> None:
        port = self.ports.pop(side, None)
        if port is not None:
            try:
                await asyncio.to_thread(port.close)
            except Exception:
                pass
        self.statuses[side].connected = False

    async def _discover(self) -> None:
        async with self._lock:
            for side, port in tuple(self.ports.items()):
                if not getattr(port, "is_open", False):
                    await self._drop(side)

            used = {
                self._path_key(str(getattr(port, "port", "")))
                for port in self.ports.values()
            }
            for side in (Side.LEFT, Side.RIGHT):
                path = self._configured(side)
                if side in self.ports or not path:
                    continue
                try:
                    port = await self._open(path)
                    self.ports[side] = port
                    used.add(self._path_key(str(getattr(port, "port", path))))
                    self.statuses[side] = WristStatus(True, None, f"SERIAL:{path}")
                except Exception as exc:
                    self.statuses[side].last_error = str(exc)

            unknown = []
            for path in self._candidates():
                if self._path_key(path) in used:
                    continue
                try:
                    port = await self._open(path)
                    side = await self._identify(port)
                    if side is not None and side not in self.ports:
                        self.ports[side] = port
                        self.statuses[side] = WristStatus(True, None, f"SERIAL:{path}")
                    else:
                        unknown.append((path, port))
                except Exception:
                    pass

            # Older firmware without identity support: deterministic fallback.
            missing = [side for side in (Side.LEFT, Side.RIGHT) if side not in self.ports]
            if len(missing) == len(unknown):
                for side, (path, port) in zip(missing, unknown):
                    self.ports[side] = port
                    self.statuses[side] = WristStatus(True, None, f"SERIAL_FALLBACK:{path}")
                unknown = []
            for _path, port in unknown:
                await asyncio.to_thread(port.close)

    async def connect(self, side: Side) -> None:
        targets = (Side.LEFT, Side.RIGHT) if side is Side.BOTH else (side,)
        if self.simulate:
            for target in targets:
                self.statuses[target] = WristStatus(True, 88, "SIM_CONNECTED")
            return
        await self._discover()
        for target in targets:
            if target not in self.ports:
                variable = "WAYBAND_LEFT_SERIAL" if target is Side.LEFT else "WAYBAND_RIGHT_SERIAL"
                error = f"{IDENTITY[target]} USB 팔찌 없음 ({variable} 확인)"
                self.statuses[target].connected = False
                self.statuses[target].last_response = f"ERROR:{error}"
                self.statuses[target].last_error = error
                raise RuntimeError(error)

    async def _write(self, side: Side, command: str) -> None:
        last_error = None
        for attempt in range(2):
            try:
                await self.connect(side)
                port = self.ports[side]
                await asyncio.to_thread(port.write, f"{command}\n".encode("ascii"))
                await asyncio.to_thread(port.flush)
                self.statuses[side].connected = True
                self.statuses[side].last_error = ""
                return
            except Exception as exc:
                last_error = exc
                await self._drop(side)
                if attempt == 0:
                    await asyncio.sleep(0.15)
        raise RuntimeError(f"{IDENTITY[side]} 쓰기 실패: {last_error}")

    def _mark(self, side: Side, pattern: PulsePattern) -> None:
        duration = (sum(pattern.pulses_ms) + sum(pattern.gaps_ms)) / 1000
        self.statuses[side].vibrating_until = time.monotonic() + duration if duration else 0

    async def _play(self, side: Side, pattern: PulsePattern) -> None:
        try:
            for index, duration in enumerate(pattern.pulses_ms):
                await self._write(side, f"{PREFIX[side]}{duration}")
                await asyncio.sleep(duration / 1000)
                if index < len(pattern.gaps_ms):
                    await asyncio.sleep(pattern.gaps_ms[index] / 1000)
            self.statuses[side].last_response = "SERIAL_DONE"
        except asyncio.CancelledError:
            try:
                await self._write(side, "X")
            except Exception:
                pass
            raise

    def _done(self, side: Side, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error:
            self.statuses[side].connected = False
            self.statuses[side].last_response = f"ERROR:{error}"
            self.statuses[side].last_error = str(error)

    async def _send_one(self, side: Side, pattern: PulsePattern) -> None:
        if self.simulate:
            self.statuses[side].last_response = "ACK:SERIAL"
            self._mark(side, pattern)
            return
        old = self._tasks.get(side)
        if old is not None and not old.done():
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        if not pattern.pulses_ms:
            await self._write(side, "X")
            self.statuses[side].last_response = "SERIAL_STOP"
            self._mark(side, pattern)
            return
        task = asyncio.create_task(self._play(side, pattern))
        task.add_done_callback(lambda done, target=side: self._done(target, done))
        self._tasks[side] = task
        self.statuses[side].last_response = "SERIAL_PLAYING"
        self._mark(side, pattern)

    async def send(self, pattern: PulsePattern) -> None:
        sides = (Side.LEFT, Side.RIGHT) if pattern.side is Side.BOTH else (pattern.side,)
        results = await asyncio.gather(
            *(self._send_one(side, pattern) for side in sides), return_exceptions=True
        )
        for side, result in zip(sides, results):
            if isinstance(result, BaseException):
                self.statuses[side].connected = False
                self.statuses[side].last_response = f"ERROR:{result}"
                self.statuses[side].last_error = str(result)

    async def maintain_connections(self, retry_seconds: float = 2.0) -> None:
        while True:
            try:
                await self.connect(Side.BOTH)
            except Exception:
                pass
            await asyncio.sleep(retry_seconds)

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if not self.simulate:
            await asyncio.gather(
                *(self._write(side, "X") for side in tuple(self.ports)),
                return_exceptions=True,
            )
        for status in self.statuses.values():
            status.vibrating_until = 0

    async def close(self) -> None:
        await asyncio.gather(
            *(self._drop(side) for side in tuple(self.ports)), return_exceptions=True
        )

    def status_text(self) -> str:
        values = []
        for side, label in ((Side.LEFT, "L"), (Side.RIGHT, "R")):
            status = self.statuses[side]
            if status.vibrating_until > time.monotonic():
                value = "vibrating"
            elif status.connected:
                value = "connected"
            elif status.last_response.startswith("ERROR:"):
                value = "missing"
            else:
                value = "waiting"
            values.append(f"{label}:{value}")
        return " / ".join(values)

    def detail_text(self) -> str:
        return " / ".join(
            f"{label}:{self.statuses[side].last_response}"
            + (f" · {self.statuses[side].last_error}" if self.statuses[side].last_error else "")
            for side, label in ((Side.LEFT, "L"), (Side.RIGHT, "R"))
        )


BleWristController = SerialWristController
