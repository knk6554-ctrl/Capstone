from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..core.events import Side
from ..core.patterns import PulsePattern

SERVICE_UUID = "7d8f1000-8e7f-4d3b-a3a6-6f44a16c1000"
COMMAND_UUID = "7d8f1001-8e7f-4d3b-a3a6-6f44a16c1000"
STATUS_UUID = "7d8f1002-8e7f-4d3b-a3a6-6f44a16c1000"
DEVICE_NAMES = {Side.LEFT: "WAYBAND_LEFT", Side.RIGHT: "WAYBAND_RIGHT"}


@dataclass(slots=True)
class WristStatus:
    connected: bool = False
    battery_percent: int | None = None
    last_response: str = "-"


@dataclass(slots=True)
class BleWristController:
    simulate: bool = False
    scan_timeout: float = 8.0
    left_serial_port: str | None = None
    left_serial_baud: int = 115200
    clients: dict[Side, object] = field(default_factory=dict)
    statuses: dict[Side, WristStatus] = field(default_factory=lambda: {Side.LEFT: WristStatus(), Side.RIGHT: WristStatus()})
    _connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
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
        if self._left_serial is not None and getattr(self._left_serial, "is_open", False):
            return
        import serial

        port = self._find_left_serial_port()
        self._left_serial = await asyncio.to_thread(
            serial.Serial, port, self.left_serial_baud, timeout=0.2, write_timeout=1
        )
        await asyncio.sleep(2.0)
        self.statuses[Side.LEFT] = WristStatus(True, None, f"SERIAL:{port}")

    async def connect(self, side: Side) -> None:
        if side is Side.BOTH:
            await asyncio.gather(self.connect(Side.LEFT), self.connect(Side.RIGHT), return_exceptions=True)
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

            device = await BleakScanner.find_device_by_name(DEVICE_NAMES[side], timeout=self.scan_timeout)
            if device is None:
                raise RuntimeError(f"{DEVICE_NAMES[side]} 검색 실패")
            client = BleakClient(device, timeout=15)
            await client.connect()
            self.clients[side] = client
            self.statuses[side].connected = True
            self.statuses[side].last_response = "CONNECTED"

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

    async def _send_one(self, side: Side, pattern: PulsePattern) -> None:
        await self._ensure(side)
        payload = pattern.wire_command().encode("ascii") if pattern.pulses_ms else b"S"
        if self.simulate:
            self.statuses[side].last_response = f"ACK:{payload.decode()}"
            return
        if side is Side.LEFT:
            await self._start_left_pattern(pattern)
            return
        client = self.clients[side]
        await client.write_gatt_char(COMMAND_UUID, payload, response=True)
        self.statuses[side].last_response = "WRITE_ACK"
        try:
            raw = await client.read_gatt_char(STATUS_UUID)
            response = bytes(raw).decode("ascii", errors="replace")
            self.statuses[side].last_response = response
            if response.startswith("BAT:"):
                self.statuses[side].battery_percent = int(response.split(":", 1)[1])
        except Exception:
            pass

    async def _write_left(self, command: str) -> None:
        if self._left_serial is None:
            raise RuntimeError("왼쪽 USB 팔찌가 연결되지 않았습니다")
        await asyncio.to_thread(self._left_serial.write, f"{command}\n".encode("ascii"))
        await asyncio.to_thread(self._left_serial.flush)

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

    async def _start_left_pattern(self, pattern: PulsePattern) -> None:
        if self._left_pattern_task is not None and not self._left_pattern_task.done():
            self._left_pattern_task.cancel()
            await asyncio.gather(self._left_pattern_task, return_exceptions=True)
        if not pattern.pulses_ms:
            await self._write_left("X")
            self.statuses[Side.LEFT].last_response = "SERIAL_STOP"
            return
        self._left_pattern_task = asyncio.create_task(self._play_left_pattern(pattern))
        self.statuses[Side.LEFT].last_response = "SERIAL_PLAYING"

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
            if status.connected:
                value = "connected"
            elif status.last_response.startswith("ERROR:"):
                value = "missing"
            else:
                value = "waiting"
            parts.append(f"{label}:{value}")
        return " / ".join(parts)

