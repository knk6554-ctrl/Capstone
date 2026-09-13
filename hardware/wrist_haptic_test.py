"""Send a three-second vibration command to left/right ESP32 wristbands over BLE."""

from __future__ import annotations

import asyncio
import sys

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

SERVICE_UUID = "7d8f1000-8e7f-4d3b-a3a6-6f44a16c1000"
COMMAND_UUID = "7d8f1001-8e7f-4d3b-a3a6-6f44a16c1000"
DEVICE_NAMES = {"L": "WAYBAND_LEFT", "R": "WAYBAND_RIGHT"}
SCAN_TIMEOUT_SECONDS = 10.0


async def send_vibration(side: str) -> None:
    name = DEVICE_NAMES[side]
    print(f"{name} 검색 중...")
    device = await BleakScanner.find_device_by_name(name, timeout=SCAN_TIMEOUT_SECONDS)
    if device is None:
        raise RuntimeError(f"{name}을 찾지 못했습니다. 전원과 BLE 광고를 확인하세요.")

    async with BleakClient(device, timeout=15.0) as client:
        service = client.services.get_service(SERVICE_UUID)
        if service is None:
            raise RuntimeError(f"{name}에 WAYBAND BLE 서비스가 없습니다.")
        characteristic = service.get_characteristic(COMMAND_UUID)
        if characteristic is None:
            raise RuntimeError(f"{name}에 진동 명령 characteristic이 없습니다.")
        await client.write_gatt_char(characteristic, b"V", response=True)
    print(f"{side}: 3초 진동 명령 전송 완료")


async def main() -> int:
    print("L=왼쪽 3초 진동, R=오른쪽 3초 진동, Q=종료")
    while True:
        command = (await asyncio.to_thread(input, "> ")).strip().upper()
        if command == "Q":
            return 0
        if command not in DEVICE_NAMES:
            print("L, R, Q 중 하나를 입력하세요.")
            continue
        try:
            await send_vibration(command)
        except (BleakError, RuntimeError, TimeoutError) as exc:
            print(f"BLE 오류: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
