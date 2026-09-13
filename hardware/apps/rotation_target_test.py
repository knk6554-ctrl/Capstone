from __future__ import annotations

import argparse
import asyncio
import math
import time

from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern
from wayband_hw.drivers.ble_wrist import BleWristController
from wayband_hw.drivers.imu import Mpu6050Yaw


async def track_target(controller: BleWristController, imu: Mpu6050Yaw, target: float, tolerance: float, timeout: float) -> bool:
    imu.reset()
    side = Side.LEFT if target < 0 else Side.RIGHT
    await controller.send(PulsePattern(side, (max(100, round(timeout * 1000)),)))
    entered_at: float | None = None
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        angle, rate = imu.update()
        error = target - angle
        print(f"\r현재 {angle:+7.2f}° / 목표 {target:+7.2f}° / 오차 {error:+7.2f}° / {rate:+6.2f}°/s", end="", flush=True)
        if abs(error) <= tolerance:
            entered_at = entered_at or time.monotonic()
            if time.monotonic() - entered_at >= 0.2:
                await controller.stop()
                print("\n목표 도달")
                return True
        else:
            entered_at = None
        if (target < 0 and angle < target - tolerance) or (target > 0 and angle > target + tolerance):
            correction = Side.RIGHT if target < 0 else Side.LEFT
            await controller.send(PulsePattern(correction, (100,), intensity=160))
        await asyncio.sleep(0.01)
    await controller.stop()
    print("\n시간 초과로 정지")
    return False


async def run(args: argparse.Namespace) -> int:
    from smbus2 import SMBus

    controller = BleWristController(simulate=args.simulate_ble)
    try:
        with SMBus(args.bus) as bus:
            imu = Mpu6050Yaw(bus, args.address, args.invert)
            print("IMU 보정 중: 장치를 움직이지 마세요.")
            imu.initialize()
            while True:
                raw = (await asyncio.to_thread(input, "목표각(-왼쪽/+오른쪽), S, Q > ")).strip().upper()
                if raw == "Q": return 0
                if raw == "S": await controller.stop(); continue
                try: target = float(raw)
                except ValueError: print("숫자 또는 S/Q를 입력하세요."); continue
                if math.isclose(target, 0, abs_tol=0.1): print("0이 아닌 각도를 입력하세요."); continue
                await track_target(controller, imu, target, args.tolerance, args.timeout)
    finally:
        await controller.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--address", type=lambda v: int(v, 0), default=0x68)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--simulate-ble", action="store_true")
    parser.add_argument("--tolerance", type=float, default=4.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
