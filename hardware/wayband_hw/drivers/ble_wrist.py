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

    async def connect(self, side: Side) -> None:
        if side is Side.BOTH:
            await asyncio.gather(self.connect(Side.LEFT), self.connect(Side.RIGHT))
            return
        if self.simulate:
            self.statuses[side] = WristStatus(True, 88, "SIM_CONNECTED")
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
        await asyncio.gather(*(self._send_one(side, pattern) for side in sides))

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
        await self.send(PulsePattern(Side.BOTH, ()))

    async def close(self) -> None:
        for client in self.clients.values():
            if getattr(client, "is_connected", False):
                await client.disconnect()
        self.clients.clear()

