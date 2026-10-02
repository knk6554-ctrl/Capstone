"""Demo 5: left/right ToF proximity, fully independent — each side only reacts to itself."""

from __future__ import annotations

import argparse
import asyncio

# demo_common installs the hardware package root before driver imports.
from demo_common import DemoRuntime, add_common_arguments, run_safely
from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern


async def demo(runtime: DemoRuntime) -> None:
    obstacle, avoidance = "장애물 없음", "직진 가능"
    while True:
        payload = await runtime.sample("좌우 근접 감시", obstacle=obstacle, avoidance=avoidance)
        left_near = (
            payload["left_mm"] is not None and payload["left_mm"] <= runtime.args.proximity_mm
        )
        right_near = (
            payload["right_mm"] is not None and payload["right_mm"] <= runtime.args.proximity_mm
        )

        if left_near and right_near:
            obstacle, avoidance = "양쪽 장애물 감지", "양쪽 주의"
        elif left_near:
            obstacle, avoidance = "좌측 장애물 감지", "좌측 주의"
        elif right_near:
            obstacle, avoidance = "우측 장애물 감지", "우측 주의"
        else:
            obstacle, avoidance = "장애물 없음", "직진 가능"

        # 왼쪽/오른쪽을 서로 독립적으로 판단한다 — 한쪽이 막혀도 다른 쪽 판정에는
        # 영향을 주지 않고, 각자 자기 쪽 손목만 울린다.
        if left_near:
            await runtime.haptic(
                "SIDE_OBSTACLE_LEFT",
                PulsePattern(Side.LEFT, (200, 200), (150,), 230),
                runtime.args.cooldown,
            )
        if right_near:
            await runtime.haptic(
                "SIDE_OBSTACLE_RIGHT",
                PulsePattern(Side.RIGHT, (200, 200), (150,), 230),
                runtime.args.cooldown,
            )

        await asyncio.sleep(runtime.args.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 좌우 근접 진동 시연")
    add_common_arguments(parser)
    parser.add_argument("--proximity-mm", type=int, default=300)
    parser.add_argument("--cooldown", type=float, default=1.0)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "5. 좌우 근접 경고")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
