from __future__ import annotations

import argparse
import asyncio

from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern
from wayband_hw.drivers.ble_wrist import BleWristController


def show_status(controller: BleWristController) -> None:
    for side in (Side.LEFT, Side.RIGHT):
        status = controller.statuses[side]
        battery = "?" if status.battery_percent is None else f"{status.battery_percent}%"
        print(f"{side.value}: connected={status.connected}, battery={battery}, response={status.last_response}")


async def run(simulate: bool) -> int:
    controller = BleWristController(simulate=simulate)
    test = {"L": Side.LEFT, "R": Side.RIGHT, "B": Side.BOTH}
    print("L=왼쪽 3초, R=오른쪽 3초, B=양쪽 3초, S=정지, I=상태, Q=종료")
    try:
        while True:
            command = (await asyncio.to_thread(input, "> ")).strip().upper()
            if command == "Q":
                await controller.stop()
                return 0
            if command == "S":
                await controller.stop()
            elif command == "I":
                show_status(controller)
                continue
            elif command in test:
                await controller.send(PulsePattern(test[command], (3000,)))
            else:
                print("L/R/B/S/I/Q 중 하나를 입력하세요.")
                continue
            show_status(controller)
    finally:
        await controller.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args().simulate)))

