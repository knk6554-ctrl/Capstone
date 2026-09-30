from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

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
    clients: dict[Side, object] = field(default_factory=dict)
    statuses: dict[Side, WristStatus] = field(default_factory=lambda: {Side.LEFT: WristStatus(), Side.RIGHT: WristStatus()})
    _connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def connect(self, side: Side) -> None:
        if side is Side.BOTH:
            await asyncio.gather(self.connect(Side.LEFT), self.connect(Side.RIGHT), return_exceptions=True)
            return
        if self.simulate:
            self.statuses[side] = WristStatus(True, 88, "SIM_CONNECTED")
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

    async def stop(self) -> None:
        if self.simulate:
            await self.send(PulsePattern(Side.BOTH, ()))
            return
        # Shutdown must never start a new BLE scan. Stop only wrists that are
        # already connected, so a missing wrist cannot crash final cleanup.
        tasks = []
        for side, client in tuple(self.clients.items()):
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

