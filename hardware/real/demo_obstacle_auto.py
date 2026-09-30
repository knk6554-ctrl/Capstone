"""Sensor-driven obstacle demo: choose side and 10-30 degree avoidance angle."""

from __future__ import annotations

import argparse
import asyncio
import statistics

from demo_common import DemoRuntime, add_common_arguments, run_safely, valid_values
from demo_obstacle import rotate
from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern


def choose_avoidance(
    front: list[int | None],
    left_mm: int | None,
    right_mm: int | None,
    *,
    obstacle_mm: int = 1000,
    side_clear_mm: int = 650,
) -> float | None:
    """Return negative=left, positive=right, None=no safe side, 0=no obstacle."""
    if len(front) != 64:
        raise ValueError("virtual front frame must contain 64 cells")

    columns: list[int | None] = []
    for column in range(8):
        values = valid_values([front[row * 8 + column] for row in range(4, 8)])
        columns.append(round(statistics.median(values)) if values else None)

    blocked = [index for index, value in enumerate(columns) if value is not None and value <= obstacle_mm]
    if len(blocked) < 2:
        return 0.0

    left_clear = left_mm is not None and left_mm >= side_clear_mm
    right_clear = right_mm is not None and right_mm >= side_clear_mm
    if not left_clear and not right_clear:
        return None

    if left_clear and not right_clear:
        direction = -1.0
    elif right_clear and not left_clear:
        direction = 1.0
    else:
        # Prefer meaningfully wider measured side. If similar, move away from
        # the horizontal center of the obstacle in the virtual front grid.
        assert left_mm is not None and right_mm is not None
        if abs(left_mm - right_mm) >= 100:
            direction = -1.0 if left_mm > right_mm else 1.0
        else:
            obstacle_center = statistics.mean(blocked)
            direction = -1.0 if obstacle_center >= 3.5 else 1.0

    nearest = min(columns[index] for index in blocked if columns[index] is not None)
    proximity = max(0.0, min(1.0, (obstacle_mm - nearest) / obstacle_mm))
    width_factor = len(blocked) / 8.0
    angle = 10.0 + 12.0 * width_factor + 8.0 * proximity
    return direction * round(max(10.0, min(30.0, angle)), 1)


async def demo(runtime: DemoRuntime) -> None:
    while True:
        payload = await runtime.sample("센서 기반 장애물 감시")
        angle = choose_avoidance(
            payload["front"],
            payload["left_mm"],
            payload["right_mm"],
            obstacle_mm=runtime.args.virtual_front_mm,
            side_clear_mm=runtime.args.side_clear_mm,
        )
        if angle == 0.0:
            await asyncio.sleep(runtime.args.interval)
            continue
        if angle is None:
            await runtime.haptic("AUTO_STOP", PulsePattern(Side.BOTH, (150, 150), (100,), 255), 1.5)
            await runtime.sample("좌우 통로 없음 · 정지", obstacle="장애물 감지", avoidance="통로 없음 · 정지", avoidance_angle=None)
            await asyncio.sleep(runtime.args.interval)
            continue

        direction = "왼쪽" if angle < 0 else "오른쪽"
        await runtime.haptic("AUTO_OBSTACLE", PulsePattern(Side.BOTH, (220, 220), (180,), 230), 2.0)
        await runtime.sample(
            f"센서 결정: {direction} {abs(angle):.1f}°",
            obstacle="장애물 감지",
            avoidance=f"{direction}으로 피함",
            avoidance_angle=angle,
        )

        if not await rotate(runtime, angle, f"{direction}으로 {abs(angle):.1f}° 회전"):
            await runtime.wait_with_sensors(2.0, "회전 시간 초과 · 안전 정지", obstacle="장애물 감지", avoidance="정지")
            continue

        await runtime.wait_with_sensors(
            runtime.args.forward_seconds,
            "자동 회피 경로 직진",
            obstacle="장애물 통과 중",
            avoidance="직진",
        )

        return_angle = -angle
        return_direction = "오른쪽" if return_angle > 0 else "왼쪽"
        if not await rotate(runtime, return_angle, f"{return_direction}으로 {abs(return_angle):.1f}° 원래 방향 복귀"):
            await runtime.wait_with_sensors(2.0, "복귀 시간 초과 · 안전 정지", avoidance="정지")
            continue

        await runtime.wait_with_sensors(2.0, "원래 방향 직진", avoidance="직진 가능")

        # Require removal before another automatic demonstration begins.
        while True:
            payload = await runtime.sample("자동 회피 완료 · 장애물 제거 대기")
            next_angle = choose_avoidance(
                payload["front"], payload["left_mm"], payload["right_mm"],
                obstacle_mm=runtime.args.virtual_front_mm,
                side_clear_mm=runtime.args.side_clear_mm,
            )
            if next_angle == 0.0:
                break
            await asyncio.sleep(runtime.args.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 센서 자동 장애물 회피 시연")
    add_common_arguments(parser)
    parser.add_argument("--virtual-front-mm", type=int, default=1000)
    parser.add_argument("--side-clear-mm", type=int, default=650)
    parser.add_argument("--forward-seconds", type=float, default=2.0)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "3-B. 센서 자동 장애물 회피")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
