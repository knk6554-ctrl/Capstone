from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core.events import Side
from ..core.patterns import PulsePattern

SERVICE_UUID = "7d8f1000-8e7f-4d3b-a3a6-6f44a16c1000"
COMMAND_UUID = "7d8f1001-8e7f-4d3b-a3a6-6f44a16c1000"
STATUS_UUID = "7d8f1002-8e7f-4d3b-a3a6-6f44a16c1000"
DEVICE_NAMES = {Side.LEFT: "WAYBAND_LEFT", Side.RIGHT: "WAYBAND_RIGHT"}
DEFAULT_RIGHT_ADDRESS = "1C:DB:D4:ED:1D:42"


@dataclass(slots=True)
class WristStatus:
    connected: bool = False
    battery_percent: int | None = None
    last_response: str = "-"
    last_error: str = ""
    vibrating_until: float = 0.0


@dataclass(slots=True)
class BleWristController:
    simulate: bool = False
    scan_timeout: float = 4.0
    connect_retries: int = 3
    right_address: str | None = field(
        default_factory=lambda: os.environ.get("WAYBAND_RIGHT_ADDRESS", DEFAULT_RIGHT_ADDRESS)
    )
    left_serial_port: str | None = None
    left_serial_baud: int = 115200
    clients: dict[Side, object] = field(default_factory=dict)
    statuses: dict[Side, WristStatus] = field(default_factory=lambda: {Side.LEFT: WristStatus(), Side.RIGHT: WristStatus()})
    _connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _left_connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _left_serial: object | None = field(default=None, init=False, repr=False)
    _left_pattern_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def _find_left_serial_port(self) -> str:
        configured = self.left_serial_port or os.environ.get("WAYBAND_LEFT_SERIAL")
        if configured:
            return configured
        for pattern in ("dev/serial/by-id/*", "dev/ttyUSB*", "dev/ttyACM*"):
            matches = sorted(Path("/").glob(pattern))
            if matches:
                return str(matches[0])
        raise RuntimeError("왼쪽 USB 팔찌를 찾지 못했습니다 (WAYBAND_LEFT_SERIAL 확인)")

    async def _connect_left_serial(self) -> None:
        async with self._left_connect_lock:
            if self._left_serial is not None and getattr(self._left_serial, "is_open", False):
                return
            import serial

            port = self._find_left_serial_port()
            self.statuses[Side.LEFT].last_response = "CONNECTING"
            self._left_serial = await asyncio.to_thread(
                serial.Serial, port, self.left_serial_baud, timeout=0.2, write_timeout=1
            )
            # CH340/ESP32 may reset when the serial port opens. A short wait is
            # sufficient and keeps first-vibration latency much lower than 2 s.
            await asyncio.sleep(0.8)
            self.statuses[Side.LEFT] = WristStatus(True, None, f"SERIAL:{port}")

    def _right_disconnected(self, _client: object) -> None:
        status = self.statuses[Side.RIGHT]
        status.connected = False
        status.last_response = "DISCONNECTED"

    async def connect(self, side: Side) -> None:
        if side is Side.BOTH:
            sides = (Side.LEFT, Side.RIGHT)
            results = await asyncio.gather(
                *(self.connect(item) for item in sides),
                return_exceptions=True,
            )
            for item, result in zip(sides, results):
                if isinstance(result, BaseException):
                    self.statuses[item].connected = False
                    self.statuses[item].last_response = f"ERROR:{result}"
            return
        if self.simulate:
            self.statuses[side] = WristStatus(True, 88, "SIM_CONNECTED")
            return
        if side is Side.LEFT:
            await self._connect_left_serial()
            return
        # BlueZ permits only one active scan at a time. Both wrists are often
        # requested concurrently, so serialize discovery and re-check after
        # waiting for the other side to finish connecting.
        async with self._connect_lock:
            client = self.clients.get(side)
            if client is not None and getattr(client, "is_connected", False):
                return
            from bleak import BleakClient, BleakScanner

            last_error: BaseException | None = None
            self.statuses[side].last_response = "CONNECTING"
            for attempt in range(1, self.connect_retries + 1):
                try:
                    if self.right_address:
                        device = await BleakScanner.find_device_by_address(
                            self.right_address,
                            timeout=self.scan_timeout,
                        )
                        if device is None:
                            device = await BleakScanner.find_device_by_name(
                                DEVICE_NAMES[side],
                                timeout=self.scan_timeout,
                            )
                    else:
                        device = await BleakScanner.find_device_by_name(
                            DEVICE_NAMES[side],
                            timeout=self.scan_timeout,
                        )
                    if device is None:
                        target = self.right_address or DEVICE_NAMES[side]
                        raise RuntimeError(f"{target} 검색 실패")
                    client = BleakClient(
                        device,
                        timeout=6,
                        disconnected_callback=self._right_disconnected,
                    )
                    await client.connect()
                    self.clients[side] = client
                    self.statuses[side].connected = True
                    self.statuses[side].last_response = "CONNECTED"
                    return
                except Exception as exc:
                    last_error = exc
                    self.clients.pop(side, None)
                    self.statuses[side].last_response = (
                        f"RETRY:{attempt}/{self.connect_retries}:{exc}"
                    )
                    self.statuses[side].last_error = str(exc)
                    if attempt < self.connect_retries:
                        await asyncio.sleep(0.5)
            raise RuntimeError(f"{DEVICE_NAMES[side]} 연결 실패: {last_error}")

    async def _ensure(self, side: Side) -> None:
        if side is Side.LEFT and not self.simulate:
            await self._connect_left_serial()
            return
        client = self.clients.get(side)
        if self.simulate or (client is not None and getattr(client, "is_connected", False)):
            return
        await self.connect(side)

    async def send(self, pattern: PulsePattern) -> None:
        sides = (Side.LEFT, Side.RIGHT) if pattern.side is Side.BOTH else (pattern.side,)
        results = await asyncio.gather(
            *(self._send_one(side, pattern) for side in sides),
            return_exceptions=True,
        )
        for side, result in zip(sides, results):
            if isinstance(result, BaseException):
                self.statuses[side].connected = False
                self.statuses[side].last_response = f"ERROR:{result}"
                self.statuses[side].last_error = str(result)

    async def _send_one(self, side: Side, pattern: PulsePattern) -> None:
        await self._ensure(side)
        payload = pattern.wire_command().encode("ascii") if pattern.pulses_ms else b"S"
        if self.simulate:
            self.statuses[side].last_response = f"ACK:{payload.decode()}"
            self._mark_vibrating(side, pattern)
            return
        if side is Side.LEFT:
            await self._start_left_pattern(pattern)
            return
        for attempt in range(2):
            try:
                client = self.clients[side]
                await client.write_gatt_char(COMMAND_UUID, payload, response=True)
                self.statuses[side].connected = True
                self.statuses[side].last_response = "WRITE_ACK"
                self.statuses[side].last_error = ""
                self._mark_vibrating(side, pattern)
                return
            except Exception:
                client = self.clients.pop(side, None)
                self.statuses[side].connected = False
                if client is not None and getattr(client, "is_connected", False):
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                if attempt == 0:
                    await self._ensure(side)
                    continue
                raise

    async def _write_left(self, command: str) -> None:
        last_error: BaseException | None = None
        for attempt in range(2):
            try:
                await self._connect_left_serial()
                if self._left_serial is None:
                    raise RuntimeError("왼쪽 USB 팔찌가 연결되지 않았습니다")
                await asyncio.to_thread(self._left_serial.write, f"{command}\n".encode("ascii"))
                await asyncio.to_thread(self._left_serial.flush)
                self.statuses[Side.LEFT].connected = True
                self.statuses[Side.LEFT].last_error = ""
                return
            except Exception as exc:
                last_error = exc
                serial_port, self._left_serial = self._left_serial, None
                if serial_port is not None:
                    try:
                        await asyncio.to_thread(serial_port.close)
                    except Exception:
                        pass
                self.statuses[Side.LEFT].connected = False
                self.statuses[Side.LEFT].last_error = str(exc)
                if attempt == 0:
                    await asyncio.sleep(0.15)
        raise RuntimeError(f"왼쪽 USB 팔찌 쓰기 실패: {last_error}")

    @staticmethod
    def _duration_seconds(pattern: PulsePattern) -> float:
        return (sum(pattern.pulses_ms) + sum(pattern.gaps_ms)) / 1000.0

    def _mark_vibrating(self, side: Side, pattern: PulsePattern) -> None:
        self.statuses[side].vibrating_until = (
            time.monotonic() + self._duration_seconds(pattern) if pattern.pulses_ms else 0.0
        )

    async def _play_left_pattern(self, pattern: PulsePattern) -> None:
        try:
            for index, duration_ms in enumerate(pattern.pulses_ms):
                await self._write_left(f"L{duration_ms}")
                await asyncio.sleep(duration_ms / 1000)
                if index < len(pattern.gaps_ms):
                    await asyncio.sleep(pattern.gaps_ms[index] / 1000)
            self.statuses[Side.LEFT].last_response = "SERIAL_DONE"
        except asyncio.CancelledError:
            await self._write_left("X")
            raise

    def _left_pattern_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            status = self.statuses[Side.LEFT]
            status.connected = False
            status.last_response = f"ERROR:{error}"
            status.last_error = str(error)
            status.vibrating_until = 0.0

    async def _start_left_pattern(self, pattern: PulsePattern) -> None:
        if self._left_pattern_task is not None and not self._left_pattern_task.done():
            self._left_pattern_task.cancel()
            await asyncio.gather(self._left_pattern_task, return_exceptions=True)
        if not pattern.pulses_ms:
            await self._write_left("X")
            self.statuses[Side.LEFT].last_response = "SERIAL_STOP"
            self.statuses[Side.LEFT].vibrating_until = 0.0
            return
        self._left_pattern_task = asyncio.create_task(self._play_left_pattern(pattern))
        self._left_pattern_task.add_done_callback(self._left_pattern_done)
        self.statuses[Side.LEFT].last_response = "SERIAL_PLAYING"
        self._mark_vibrating(Side.LEFT, pattern)

    async def maintain_connections(self, retry_seconds: float = 2.0) -> None:
        """Keep both transports warm so a haptic command never has to scan first."""
        while True:
            await self.connect(Side.BOTH)
            await asyncio.sleep(retry_seconds)

    async def stop(self) -> None:
        if self.simulate:
            await self.send(PulsePattern(Side.BOTH, ()))
            return
        if self._left_pattern_task is not None and not self._left_pattern_task.done():
            self._left_pattern_task.cancel()
            await asyncio.gather(self._left_pattern_task, return_exceptions=True)
        if self._left_serial is not None and getattr(self._left_serial, "is_open", False):
            try:
                await self._write_left("X")
            except Exception:
                pass
        # Shutdown must never start a new BLE scan. Stop only wrists that are
        # already connected, so a missing wrist cannot crash final cleanup.
        tasks = []
        for side, client in tuple(self.clients.items()):
            if side is Side.LEFT:
                continue
            if getattr(client, "is_connected", False):
                tasks.append(client.write_gatt_char(COMMAND_UUID, b"S", response=True))
            else:
                self.statuses[side].connected = False
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for status in self.statuses.values():
            status.vibrating_until = 0.0

    async def close(self) -> None:
        for client in tuple(self.clients.values()):
            if getattr(client, "is_connected", False):
                try:
                    await client.disconnect()
                except Exception:
                    pass
        self.clients.clear()
        if self._left_serial is not None:
            try:
                await asyncio.to_thread(self._left_serial.close)
            except Exception:
                pass
            self._left_serial = None

    def status_text(self) -> str:
        parts = []
        for side, label in ((Side.LEFT, "L"), (Side.RIGHT, "R")):
            status = self.statuses[side]
            if status.vibrating_until > time.monotonic():
                value = "vibrating"
            elif status.connected:
                value = "connected"
            elif status.last_response == "CONNECTING" or status.last_response.startswith("RETRY:"):
                value = "connecting"
            elif status.last_response.startswith("ERROR:"):
                value = "missing"
            else:
                value = "waiting"
            parts.append(f"{label}:{value}")
        return " / ".join(parts)

    def detail_text(self) -> str:
        parts = []
        for side, label in ((Side.LEFT, "L"), (Side.RIGHT, "R")):
            status = self.statuses[side]
            detail = status.last_response
            if status.last_error:
                detail += f" · {status.last_error}"
            parts.append(f"{label}:{detail}")
        return " / ".join(parts)

