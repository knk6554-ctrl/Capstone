"""Demo 1: stair/drop detection with continuous sensor telemetry."""

from __future__ import annotations

import argparse
import asyncio

# demo_common installs the hardware package root before driver imports.
from demo_common import DemoRuntime, add_common_arguments, run_safely
from wayband_hw.core.detection import EnvironmentDetector
from wayband_hw.core.events import EventKind


async def demo(runtime: DemoRuntime) -> None:
    detector = EnvironmentDetector(
        runtime.cfg.baseline_down_mm,
        drop_delta_mm=runtime.cfg.down_drop_delta_mm,
        rise_delta_mm=runtime.cfg.stair_rise_delta_mm,
    )
    detector.gate.required = runtime.cfg.required_frames
    while True:
        payload = await runtime.sample("계단·낙차 감시")
        events = detector.evaluate([None] * 64, payload["down"])
        event = next(
            (item for item in events if item.kind in {EventKind.DOWN_DANGER, EventKind.STAIR_DOWN}),
            None,
        )
        if event is not None:
            label = "낙차 위험" if event.kind is EventKind.DOWN_DANGER else "하행 계단 감지"
            await runtime.event_haptic(event)
            await runtime.sample("계단 진동 안내", stairs=label)
        await asyncio.sleep(runtime.args.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 계단 감지 시연")
    add_common_arguments(parser)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "1. 계단 감지")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
