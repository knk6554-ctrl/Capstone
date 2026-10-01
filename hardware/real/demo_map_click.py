"""Demo 4: map demo-point clicks to wrist haptics while sensors stay live."""

from __future__ import annotations

import argparse
import asyncio

from control import CommandKind
from map_api import MapApi
from demo_common import (
    ARRIVAL_PATTERN,
    CROSSWALK_PATTERN,
    LEFT_TURN_PATTERN,
    RIGHT_TURN_PATTERN,
    DemoRuntime,
    add_common_arguments,
    run_safely,
)


async def demo(runtime: DemoRuntime) -> None:
    api = MapApi(runtime.args.server_url)
    queue: asyncio.Queue = asyncio.Queue()
    receiver = asyncio.create_task(api.pump(queue))
    try:
        while True:
            await runtime.sample("지도 시연 포인트 클릭 대기")
            while not queue.empty():
                command = queue.get_nowait()
                if command.kind is CommandKind.TURN and command.angle_degrees is not None:
                    left = command.angle_degrees < 0
                    await runtime.haptic(
                        "CLICK_LEFT" if left else "CLICK_RIGHT",
                        LEFT_TURN_PATTERN if left else RIGHT_TURN_PATTERN,
                        1.5,
                        source_latency_ms=command.latency_ms,
                    )
                    await runtime.sample("클릭 좌회전 진동" if left else "클릭 우회전 진동")
                elif command.kind is CommandKind.CROSSWALK:
                    await runtime.haptic(
                        "CLICK_CROSSWALK", CROSSWALK_PATTERN, 1.5,
                        source_latency_ms=command.latency_ms,
                    )
                    await runtime.sample("클릭 횡단보도 진동")
                elif command.kind is CommandKind.ARRIVED:
                    await runtime.haptic(
                        "CLICK_ARRIVAL", ARRIVAL_PATTERN, 3.0,
                        source_latency_ms=command.latency_ms,
                    )
                    await runtime.sample("클릭 도착 진동")
            await asyncio.sleep(0.05)
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 지도 클릭 진동 시연")
    add_common_arguments(parser)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "4. 지도 클릭")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
