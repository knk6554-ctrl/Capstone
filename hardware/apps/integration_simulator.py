from __future__ import annotations

import argparse
import asyncio

from wayband_hw.core.detection import EnvironmentDetector
from wayband_hw.core.events import EventKind, WaybandEvent
from wayband_hw.core.priority import PriorityManager
from wayband_hw.drivers.ble_wrist import BleWristController

MAP_COMMANDS = {"L": EventKind.TURN_LEFT, "R": EventKind.TURN_RIGHT, "G": EventKind.GO_STRAIGHT, "A": EventKind.ARRIVED, "U": EventKind.UTURN}


async def run(simulate_ble: bool) -> int:
    controller = BleWristController(simulate=simulate_ble); manager = PriorityManager(); detector = EnvironmentDetector(700)
    print("수동 통합 시험: L/R/G/A/U=지도, F=전방장애물, D=낙차, UL/DL=계단, BL/BR=회전막힘, S=정지, Q=종료")
    try:
        while True:
            raw = (await asyncio.to_thread(input, "> ")).strip().upper()
            if raw == "Q": await controller.stop(); return 0
            if raw == "S": await controller.stop(); manager.reset(); print("모든 진동 정지"); continue
            if raw in MAP_COMMANDS: event = WaybandEvent(MAP_COMMANDS[raw], "MANUAL_MAP")
            elif raw == "F": event = WaybandEvent(EventKind.FRONT_DANGER, "SIM_TOF", distance_mm=550)
            elif raw == "D": event = WaybandEvent(EventKind.DOWN_DANGER, "SIM_TOF")
            elif raw == "UL": event = WaybandEvent(EventKind.STAIR_UP, "SIM_TOF")
            elif raw == "DL": event = WaybandEvent(EventKind.STAIR_DOWN, "SIM_TOF")
            elif raw == "BL": event = WaybandEvent(EventKind.TURN_BLOCKED_LEFT, "SIM_TOF")
            elif raw == "BR": event = WaybandEvent(EventKind.TURN_BLOCKED_RIGHT, "SIM_TOF")
            else: print("알 수 없는 명령"); continue
            selected = manager.choose([event])
            if selected is None: print("재알림 대기 시간 중"); continue
            chosen, pattern = selected; await controller.send(pattern)
            print(f"{chosen.kind.value} priority={chosen.priority} side={pattern.side.value} wire={pattern.wire_command()}")
    finally: await controller.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--real-ble", action="store_true")
    raise SystemExit(asyncio.run(run(not parser.parse_args().real_ble)))

