"""Demo 3: front obstacle -> check left, fall back to right, keep the new heading."""

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
        f"ROTATE_{side.value}",
        PulsePattern(side, (round(runtime.cfg.rotation_timeout_seconds * 1000),), intensity=220),
        0.5,
    )
    started = time.monotonic()
    last_display = 0.0
    avoidance = "좌측으로 피함" if target < 0 else "우측으로 피함"
    try:
        while time.monotonic() - started < runtime.cfg.rotation_timeout_seconds:
            if runtime.args.simulate_sensors:
                await runtime.sample(label, obstacle="장애물 감지", avoidance=avoidance, avoidance_angle=target)
                if time.monotonic() - started >= 1.0:
                    return True
                await asyncio.sleep(runtime.args.interval)
                continue

            # Mpu6050Yaw.update()는 호출 간격이 0.1초를 넘으면 그 초과분을 그냥
            # 버린다. runtime.sample()은 ToF 3개를 순서대로 읽는 느린 호출이라
            # 매번 그걸 기다리고 나서 update()를 부르면 실제 회전각보다 적게
            # 누적된다 — 각도 확인은 IMU만 직접, 빠르게 돌리고, 화면 표시용
            # 전체 샘플링은 따로 느리게(0.2초마다) 한다.
            angle, _rate = runtime.imu.update() if runtime.imu is not None else (0.0, 0.0)
            now = time.monotonic()
            if now - last_display >= 0.2:
                last_display = now
                await runtime.sample(label, obstacle="장애물 감지", avoidance=avoidance, avoidance_angle=target)
            if (target < 0 and angle <= target + runtime.cfg.rotation_tolerance_degrees) or (
                target > 0 and angle >= target - runtime.cfg.rotation_tolerance_degrees
            ):
                return True
            await asyncio.sleep(0.01)
        return False
    finally:
        await runtime.wrists.stop()


async def demo(runtime: DemoRuntime) -> None:
    blocked_frames = 0
    while True:
        payload = await runtime.sample("장애물 배치 대기")
        front_blocked = virtual_front_blocked(payload["front"], runtime.args.virtual_front_mm)
        if not front_blocked:
            blocked_frames = 0
            await asyncio.sleep(runtime.args.interval)
            continue
        blocked_frames += 1
        if blocked_frames < runtime.args.obstacle_confirm_frames:
            await runtime.sample(
                f"장애물 후보 확인 {blocked_frames}/{runtime.args.obstacle_confirm_frames}",
                obstacle="장애물 확인 중",
                avoidance="판정 대기",
            )
            await asyncio.sleep(runtime.args.interval)
            continue
        blocked_frames = 0

        # 1. 전방 장애물 감지 -> 양쪽 팔찌 진동
        await runtime.haptic("OBSTACLE", PulsePattern(Side.BOTH, (220, 220), (180,), 230), 2.0)
        payload = await runtime.sample(
            "전방 장애물 확인 · 좌측 확인 중",
            obstacle="장애물 감지",
            avoidance="좌측 확인 중",
        )

        # 2. 왼쪽부터 확인한다 — 막혀 있으면 왼쪽 진동으로 알리고 중앙으로 복귀한 뒤 오른쪽을 확인한다.
        left_blocked = (
            payload["left_mm"] is not None and payload["left_mm"] <= runtime.args.left_blocked_mm
        )

        if left_blocked:
            await runtime.haptic("LEFT_BLOCKED", PulsePattern(Side.LEFT, (200, 200), (150,), 240), 1.5)
            await runtime.wait_with_sensors(
                1.0,
                "좌측 막힘 · 중앙 복귀",
                obstacle="장애물 감지",
                avoidance="중앙 복귀",
            )
            payload = await runtime.sample(
                "우측 확인 중",
                obstacle="장애물 감지",
                avoidance="우측 확인 중",
            )
            right_blocked = (
                payload["right_mm"] is not None
                and payload["right_mm"] <= runtime.args.right_blocked_mm
            )
            if right_blocked:
                await runtime.haptic(
                    "STOP_NO_PATH", PulsePattern(Side.BOTH, (150, 150), (100,), 255), 1.5
                )
                await runtime.wait_with_sensors(
                    2.0,
                    "좌우 모두 막힘 · 정지",
                    obstacle="장애물 감지",
                    avoidance="통로 없음 · 정지",
                    avoidance_angle=None,
                )
                continue
            target = 30.0
            label = "오른쪽으로 30° 회전"
            await runtime.sample(
                "우측 열림 확인",
                obstacle="장애물 감지",
                avoidance="우측 30° 회피 결정",
                avoidance_angle=target,
            )
        else:
            target = -30.0
            label = "왼쪽으로 30° 회전"
            await runtime.sample(
                "좌측 열림 확인",
                obstacle="장애물 감지",
                avoidance="좌측 30° 회피 결정",
                avoidance_angle=target,
            )

        # 3. 열린 방향으로 30도 회전한다. 회전 중 장애물이 없으면(진동이 더 울리지 않으면) 그대로 진행.
        turned_ok = await rotate(runtime, target, label)
        if not turned_ok:
            await runtime.sample("회전 시간 초과 · 정지", obstacle="장애물 감지", avoidance="정지")
            await runtime.wait_with_sensors(2.0, "안전 정지", obstacle="장애물 감지", avoidance="정지")
            continue

        # 4. 회피 후 원래 방향으로 되돌아가지 않고, 새로 돌아본 방향을 그대로 유지한 채 직진한다.
        await runtime.wait_with_sensors(
            runtime.args.forward_seconds,
            "회피 경로 직진 · 새 방향 유지",
            obstacle="장애물 통과 중",
            avoidance="새 방향으로 직진",
        )

        # Do not immediately retrigger while the demonstration boxes remain.
        clear_frames = 0
        while True:
            payload = await runtime.sample("시연 완료 · 장애물 제거 대기", avoidance="새 방향으로 직진")
            clear = not virtual_front_blocked(payload["front"], runtime.args.virtual_front_mm)
            clear_frames = clear_frames + 1 if clear else 0
            if clear_frames >= runtime.args.obstacle_clear_frames:
                break
            await asyncio.sleep(runtime.args.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 장애물 회피 시연")
    add_common_arguments(parser)
    parser.add_argument("--virtual-front-mm", type=int, default=1000)
    parser.add_argument("--right-blocked-mm", type=int, default=650)
    parser.add_argument("--left-blocked-mm", type=int, default=650)
    parser.add_argument("--forward-seconds", type=float, default=2.0)
    parser.add_argument("--obstacle-confirm-frames", type=int, default=3)
    parser.add_argument("--obstacle-clear-frames", type=int, default=5)
    args = parser.parse_args()
    runtime = DemoRuntime(args, "3. 장애물 회피")
    asyncio.run(run_safely(runtime, demo))


if __name__ == "__main__":
    main()
