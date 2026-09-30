"""Demo 3: virtual-front/right obstacle, left 30 deg, forward, right 30 deg."""

from __future__ import annotations

import argparse
import asyncio
import time

# demo_common installs the hardware package root before driver imports.
from demo_common import (
    LEFT_TURN_PATTERN,
    RIGHT_TURN_PATTERN,
    DemoRuntime,
    add_common_arguments,
    run_safely,
    virtual_front_blocked,
)
from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern


async def rotate(runtime: DemoRuntime, target: float, label: str) -> bool:
    runtime.reset_angle()
    side = Side.LEFT if target < 0 else Side.RIGHT
    await runtime.haptic(
        f"ROTATE_{side.value}_{time.monotonic()}",
        PulsePattern(side, (round(runtime.cfg.rotation_timeout_seconds * 1000),), intensity=220),
        0.0,
    )
    started = time.monotonic()
    try:
        while time.monotonic() - started < runtime.cfg.rotation_timeout_seconds:
            payload = await runtime.sample(
                label,
                obstacle="장애물 감지",
                avoidance="좌측으로 피함" if target < 0 else "원래 방향 복귀",
                avoidance_angle=target,
            )
            angle = payload["angle_deg"]
            if runtime.args.simulate_sensors:
                if time.monotonic() - started >= 1.0:
                    return True
            elif (target < 0 and angle <= target + runtime.cfg.rotation_tolerance_degrees) or (
                target > 0 and angle >= target - runtime.cfg.rotation_tolerance_degrees
            ):
                return True
            await asyncio.sleep(runtime.args.interval)
        return False
    finally:
        await runtime.wrists.stop()


async def demo(runtime: DemoRuntime) -> None:
    while True:
        payload = await runtime.sample("장애물 배치 대기")
        front_blocked = virtual_front_blocked(payload["front"], runtime.args.virtual_front_mm)
        right_blocked = (
            payload["right_mm"] is not None
            and payload["right_mm"] <= runtime.args.right_blocked_mm
        )
        if not (front_blocked and right_blocked):
            await asyncio.sleep(runtime.args.interval)
            continue

        await runtime.haptic("OBSTACLE", PulsePattern(Side.BOTH, (220, 220), (180,), 230), 2.0)
        await runtime.sample(
            "전방 하단·우측 장애물 확인",
            obstacle="장애물 감지",
            avoidance="좌측 30° 회피 결정",
            avoidance_angle=-30.0,
        )

        left_ok = await rotate(runtime, -30.0, "왼쪽으로 30° 회전")
        if not left_ok:
            await runtime.sample("왼쪽 회전 시간 초과 · 정지", obstacle="장애물 감지", avoidance="정지")
            await runtime.wait_with_sensors(2.0, "안전 정지", obstacle="장애물 감지", avoidance="정지")
            continue

        await runtime.wait_with_sensors(
            runtime.args.forward_seconds,
            "회피 경로 직진",
            obstacle="장애물 통과 중",
            avoidance="직진",
        )

        right_ok = await rotate(runtime, 30.0, "오른쪽으로 30° 회전 · 원래 방향 복귀")
        if not right_ok:
            await runtime.sample("복귀 회전 시간 초과 · 정지", obstacle="장애물 통과", avoidance="정지")
            await runtime.wait_with_sensors(2.0, "안전 정지", avoidance="정지")
            continue

        await runtime.wait_with_sensors(2.0, "원래 방향 직진", avoidance="직진 가능")
        # Do not immediately retrigger while the demonstration boxes remain.
        while True:
            payload = await runtime.sample("시연 완료 · 장애물 제거 대기")
            if not virtual_front_blocked(payload["front"], runtime.args.virtual_front_mm):
                break
            await asyncio.sleep(runtime.args.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 장애물 회피 시연")
    add_common_arguments(parser)
    parser.add_argument("--virtual-front-mm", type=int, default=1000)
    parser.add_argument("--right-blocked-mm", type=int, default=650)
    parser.add_argument("--forward-seconds", type=float, default=2.0)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "3. 장애물 회피")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
