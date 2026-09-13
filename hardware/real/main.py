from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import deque
from pathlib import Path
from urllib.error import URLError

HARDWARE_ROOT = Path(__file__).resolve().parents[1]
if str(HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(HARDWARE_ROOT))

from wayband_hw.core.detection import EnvironmentDetector
from wayband_hw.core.events import EventKind, Side
from wayband_hw.core.patterns import PulsePattern, pattern_for
from wayband_hw.drivers.ble_wrist import BleWristController
from wayband_hw.drivers.imu import Mpu6050Yaw

from config import Config
from control import (
    ARRIVED_PATTERN,
    CROSSWALK_PATTERN,
    FRONT_WARNING_PATTERN,
    ROTATION_FAILED_PATTERN,
    STRAIGHT_PATTERN,
    CommandKind,
    RotationController,
    front_is_blocked,
    plan_avoidance_angle,
)
from map_api import MapApi
from sensors import SimulatedRig, TofRig


async def run(args: argparse.Namespace) -> None:
    cfg = Config(
        server_url=args.server_url,
        baseline_down_mm=args.baseline_down_mm,
        imu_invert=args.invert_imu,
    )
    rig = SimulatedRig(cfg) if args.simulate_sensors else TofRig(cfg)
    wrists = BleWristController(simulate=args.simulate_ble)
    api = MapApi(cfg.server_url)
    detector = EnvironmentDetector(
        cfg.baseline_down_mm,
        obstacle_mm=cfg.front_warning_mm,
        drop_delta_mm=cfg.down_drop_delta_mm,
        rise_delta_mm=cfg.stair_rise_delta_mm,
    )
    detector.gate.required = cfg.required_frames
    pending_navigation = deque()
    avoidance_angle: float | None = None
    avoidance_clear_count = 0
    last_poll = 0.0
    last_safety: dict[EventKind, float] = {}
    imu_bus = None

    rig.start()
    if args.simulate_imu:
        class SimulatedImu:
            def reset(self): pass
            def update(self): return 0.0, 0.0
        imu = SimulatedImu()
    else:
        from smbus2 import SMBus
        imu_bus = SMBus(cfg.i2c_bus)
        imu = Mpu6050Yaw(imu_bus, cfg.imu_address, cfg.imu_invert)
        print("IMU 보정 중입니다. 장치를 움직이지 마세요.")
        imu.initialize()
    rotation = RotationController(
        wrists,
        imu,
        tolerance_degrees=cfg.rotation_tolerance_degrees,
        timeout_seconds=cfg.rotation_timeout_seconds,
        simulate=args.simulate_imu,
    )

    print("WayBand real 제어 시작. Ctrl+C로 안전 정지합니다.")
    try:
        while True:
            now = time.monotonic()
            if now - last_poll >= 0.4:
                last_poll = now
                try:
                    pending_navigation.extend(await asyncio.to_thread(api.poll))
                except (URLError, TimeoutError, OSError) as exc:
                    print(f"지도 서버 대기: {exc}")

            snapshot = await asyncio.to_thread(rig.snapshot)
            if snapshot is None:
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue
            front, down, left_mm, right_mm = snapshot
            safety_events = detector.evaluate(front, down)

            # 낙차/계단은 지도 및 회피 안내보다 항상 먼저 처리한다.
            urgent = [event for event in safety_events if event.kind is not EventKind.FRONT_DANGER]
            if urgent:
                event = max(urgent, key=lambda item: item.priority)
                cooldown = pattern_for(event).repeat_after_ms / 1000.0
                if now - last_safety.get(event.kind, -1e9) >= cooldown:
                    await wrists.send(pattern_for(event))
                    last_safety[event.kind] = now
                    print(f"안전 경고: {event.kind.value}")
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue

            blocked = front_is_blocked(front, cfg.front_warning_mm)
            if avoidance_angle is None and blocked:
                await wrists.send(FRONT_WARNING_PATTERN)
                angle = plan_avoidance_angle(
                    front,
                    left_mm,
                    right_mm,
                    horizontal_fov_degrees=cfg.tof_horizontal_fov_degrees,
                    obstacle_mm=cfg.front_warning_mm,
                    side_clear_mm=cfg.side_clear_mm,
                    minimum_corridor_width_mm=cfg.minimum_corridor_width_mm,
                )
                if angle is None or angle == 0:
                    await wrists.send(ROTATION_FAILED_PATTERN)
                    print("안전한 회피 통로가 없어 정지합니다.")
                else:
                    ok = await rotation.rotate(angle)
                    if ok:
                        avoidance_angle = angle
                        avoidance_clear_count = 0
                        print(f"회피 시작: {angle:+.1f}°")
                    else:
                        await wrists.send(ROTATION_FAILED_PATTERN)
                        print("회피 목표각 10초 타임아웃")
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue

            if avoidance_angle is not None:
                obstacle_side = left_mm if avoidance_angle > 0 else right_mm
                clear = not blocked and obstacle_side is not None and obstacle_side >= cfg.side_clear_mm
                avoidance_clear_count = avoidance_clear_count + 1 if clear else 0
                if avoidance_clear_count >= cfg.avoidance_clear_frames:
                    ok = await rotation.rotate(-avoidance_angle)
                    if ok:
                        print(f"원래 방향 복귀: {-avoidance_angle:+.1f}°")
                        await wrists.send(STRAIGHT_PATTERN)
                    else:
                        await wrists.send(ROTATION_FAILED_PATTERN)
                        print("복귀 목표각 10초 타임아웃")
                    avoidance_angle = None
                    avoidance_clear_count = 0
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue

            if pending_navigation:
                command = pending_navigation.popleft()
                if command.kind is CommandKind.CROSSWALK:
                    await wrists.send(CROSSWALK_PATTERN)
                    print("횡단보도: 정지하고 보행 신호를 확인하세요.")
                elif command.kind is CommandKind.ARRIVED:
                    await wrists.send(ARRIVED_PATTERN)
                    print("목적지 도착")
                elif command.kind is CommandKind.TURN and command.angle_degrees is not None:
                    side_distance = left_mm if command.angle_degrees < 0 else right_mm
                    if side_distance is None or side_distance <= cfg.side_blocked_mm:
                        side = Side.LEFT if command.angle_degrees < 0 else Side.RIGHT
                        await wrists.send(PulsePattern(side, (150, 150, 150), (100, 100), 255))
                        print("회전 방향이 막혀 지도 회전을 취소했습니다.")
                    elif not await rotation.rotate(command.angle_degrees):
                        await wrists.send(ROTATION_FAILED_PATTERN)
                        print("지도 목표각 10초 타임아웃")
                    else:
                        print(f"지도 회전 완료: {command.angle_degrees:+.1f}°")

            await asyncio.sleep(cfg.loop_interval_seconds)
    finally:
        await wrists.stop()
        await wrists.close()
        rig.close()
        if imu_bus is not None:
            imu_bus.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WayBand 카카오 길안내 + 8x8 ToF + IMU 실전 제어기")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument("--baseline-down-mm", type=int, default=700)
    parser.add_argument("--invert-imu", action="store_true")
    parser.add_argument("--simulate-sensors", action="store_true")
    parser.add_argument("--simulate-ble", action="store_true")
    parser.add_argument("--simulate-imu", action="store_true")
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        print("\n안전 정지 완료")
