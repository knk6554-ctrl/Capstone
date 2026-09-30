"""Demo 2: route GPS commands limited to left/crosswalk/right/arrival."""

from __future__ import annotations

import argparse
import asyncio
from urllib.error import URLError

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
    while True:
        await runtime.sample("GPS 경로 안내 대기")
        try:
            commands = await asyncio.to_thread(api.poll)
        except (URLError, TimeoutError, OSError):
            commands = []
        for command in commands:
            if command.kind is CommandKind.TURN and command.angle_degrees is not None:
                if command.angle_degrees < 0:
                    await runtime.haptic("GPS_LEFT", LEFT_TURN_PATTERN, 2.0)
                    await runtime.sample("GPS 좌회전 진동")
                else:
                    await runtime.haptic("GPS_RIGHT", RIGHT_TURN_PATTERN, 2.0)
                    await runtime.sample("GPS 우회전 진동")
            elif command.kind is CommandKind.CROSSWALK:
                await runtime.haptic("GPS_CROSSWALK", CROSSWALK_PATTERN, 2.0)
                await runtime.sample("GPS 횡단보도 진동")
            elif command.kind is CommandKind.ARRIVED:
                await runtime.haptic("GPS_ARRIVAL", ARRIVAL_PATTERN, 5.0)
                await runtime.sample("목적지 도착 진동")
        await asyncio.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand GPS 경로 진동 시연")
    add_common_arguments(parser)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "2. GPS 경로")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
