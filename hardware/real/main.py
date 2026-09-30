from __future__ import annotations

import argparse
import asyncio
import sys
import threading
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
    STAIRS_PATTERN,
    STRAIGHT_PATTERN,
    CommandKind,
    RotationController,
    front_is_blocked,
    plan_avoidance_angle,
)
from map_api import MapApi
from sensors import SimulatedRig, TofRig
from sensor_dashboard import SharedState, render_terminal


def _dashboard_loop(state: SharedState, stop: threading.Event) -> None:
    while not stop.wait(0.25):
        print("\033[2J\033[H" + render_terminal(state.get()), end="", flush=True)


def _dashboard_payload(
    *,
    front,
    down,
    left_mm,
    right_mm,
    angle,
    rate,
    safety_events,
    blocked,
    avoidance_angle,
    action,
    simulated,
):
    kinds = {event.kind for event in safety_events}
    if EventKind.STAIR_UP in kinds:
        stairs = "상행 계단 감지"
    elif EventKind.STAIR_DOWN in kinds:
        stairs = "하행 계단 감지"
    elif EventKind.DOWN_DANGER in kinds:
        stairs = "낙차 위험"
    else:
        stairs = "계단 없음"

    obstacle = "장애물 감지" if blocked else "장애물 없음"
    if avoidance_angle is None:
        avoidance = "통로 탐색 중" if blocked else "직진 가능"
    elif avoidance_angle < 0:
        avoidance = "좌측으로 피함"
    elif avoidance_angle > 0:
        avoidance = "우측으로 피함"
    else:
        avoidance = "직진 가능"
    valid_front = [value for value in front if value is not None]
    valid_down = [value for value in down if value is not None]
    return {
        "timestamp": time.time(),
        "source": "모의 센서" if simulated else "실제 센서",
        "front": front,
        "down": down,
        "front_nearest_mm": min(valid_front) if valid_front else None,
        "down_median_mm": sorted(valid_down)[len(valid_down) // 2] if valid_down else None,
        "left_mm": left_mm,
        "right_mm": right_mm,
        "angle_deg": round(angle, 1),
        "rate_dps": round(rate, 1),
        "obstacle": obstacle,
        "stairs": stairs,
        "avoidance": avoidance,
        "avoidance_angle_deg": avoidance_angle,
        "haptic_status": action,
    }


async def run(args: argparse.Namespace) -> None:
    if args.map_only:
        await run_map_only(args)
        return
    cfg = Config(
        server_url=args.server_url,
        baseline_down_mm=args.baseline_down_mm,
        imu_invert=args.invert_imu,
        enable_front=not args.skip_front,
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
    dashboard_state = SharedState({"error": "센서 초기화 중입니다."})
    dashboard_stop = threading.Event()
    dashboard_thread = None
    current_action = "시스템 준비 중"

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

    def update_rotation_telemetry(angle: float, rate: float) -> None:
        if not args.terminal:
            return
        payload = dashboard_state.get()
        if "front" not in payload:
            return
        payload["angle_deg"] = round(angle, 1)
        payload["rate_dps"] = round(rate, 1)
        dashboard_state.set(payload)

    rotation = RotationController(
        wrists,
        imu,
        tolerance_degrees=cfg.rotation_tolerance_degrees,
        timeout_seconds=cfg.rotation_timeout_seconds,
        simulate=args.simulate_imu,
        telemetry_callback=update_rotation_telemetry,
    )

    if args.terminal:
        dashboard_thread = threading.Thread(
            target=_dashboard_loop,
            args=(dashboard_state, dashboard_stop),
            daemon=True,
        )
        dashboard_thread.start()

    def publish_action(message: str, avoidance_target="unchanged") -> None:
        nonlocal current_action
        current_action = message
        if not args.terminal:
            return
        payload = dashboard_state.get()
        if "front" not in payload:
            return
        payload["haptic_status"] = message
        if avoidance_target != "unchanged":
            payload["avoidance_angle_deg"] = avoidance_target
            if avoidance_target is None:
                payload["avoidance"] = "통로 없음 · 정지"
            elif avoidance_target < 0:
                payload["avoidance"] = "좌측으로 피함"
            elif avoidance_target > 0:
                payload["avoidance"] = "우측으로 피함"
            else:
                payload["avoidance"] = "직진 가능"
        dashboard_state.set(payload)

    if args.obstacle_only:
        print("WayBand 장애물 센서 전용 모드 시작. Ctrl+C로 안전 정지합니다.")
    else:
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
            imu_angle, imu_rate = imu.update()
            blocked = front_is_blocked(front, cfg.front_warning_mm)

            if args.terminal:
                dashboard_state.set(_dashboard_payload(
                    front=front,
                    down=down,
                    left_mm=left_mm,
                    right_mm=right_mm,
                    angle=imu_angle,
                    rate=imu_rate,
                    safety_events=safety_events,
                    blocked=blocked,
                    avoidance_angle=avoidance_angle,
                    action=current_action,
                    simulated=args.simulate_sensors,
                ))

            # 낙차/계단은 지도 및 회피 안내보다 항상 먼저 처리한다.
            urgent = [event for event in safety_events if event.kind is not EventKind.FRONT_DANGER]
            if urgent:
                event = max(urgent, key=lambda item: item.priority)
                cooldown = pattern_for(event).repeat_after_ms / 1000.0
                if now - last_safety.get(event.kind, -1e9) >= cooldown:
                    await wrists.send(pattern_for(event))
                    last_safety[event.kind] = now
                    current_action = f"{event.detail or event.kind.value} 진동 전송"
                    print(f"안전 경고: {event.kind.value}")
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue

            if avoidance_angle is None and blocked:
                await wrists.send(FRONT_WARNING_PATTERN)
                current_action = "전방 장애물 진동 전송 · 회피 통로 계산"
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
                    current_action = "안전한 회피 통로 없음 · 정지"
                    print("안전한 회피 통로가 없어 정지합니다.")
                else:
                    publish_action(
                        f"{'좌측' if angle < 0 else '우측'} {abs(angle):.1f}° 회전 안내",
                        angle,
                    )
                    ok = await rotation.rotate(angle)
                    if ok:
                        avoidance_angle = angle
                        avoidance_clear_count = 0
                        current_action = "장애물 옆으로 전진"
                        print(f"회피 시작: {angle:+.1f}°")
                    else:
                        await wrists.send(ROTATION_FAILED_PATTERN)
                        current_action = "회피 회전 10초 타임아웃"
                        print("회피 목표각 10초 타임아웃")
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue

            if avoidance_angle is not None:
                obstacle_side = left_mm if avoidance_angle > 0 else right_mm
                clear = not blocked and obstacle_side is not None and obstacle_side >= cfg.side_clear_mm
                avoidance_clear_count = avoidance_clear_count + 1 if clear else 0
                if avoidance_clear_count >= cfg.avoidance_clear_frames:
                    publish_action(f"원래 방향으로 {-avoidance_angle:+.1f}° 복귀 안내")
                    ok = await rotation.rotate(-avoidance_angle)
                    if ok:
                        print(f"원래 방향 복귀: {-avoidance_angle:+.1f}°")
                        await wrists.send(STRAIGHT_PATTERN)
                        current_action = "원래 진행 방향 복귀 완료 · 직진"
                    else:
                        await wrists.send(ROTATION_FAILED_PATTERN)
                        current_action = "방향 복귀 10초 타임아웃"
                        print("복귀 목표각 10초 타임아웃")
                    avoidance_angle = None
                    avoidance_clear_count = 0
                await asyncio.sleep(cfg.loop_interval_seconds)
                continue

            if pending_navigation:
                command = pending_navigation.popleft()
                if command.kind is CommandKind.CROSSWALK:
                    await wrists.send(CROSSWALK_PATTERN)
                    current_action = "횡단보도 도착 · 양쪽 팔찌 진동"
                    print("횡단보도: 정지하고 보행 신호를 확인하세요.")
                elif command.kind is CommandKind.STAIRS:
                    await wrists.send(STAIRS_PATTERN)
                    current_action = "지도 계단 구간 · 양쪽 팔찌 진동"
                    print("계단: 정지하고 발밑을 확인하세요.")
                elif command.kind is CommandKind.ARRIVED:
                    await wrists.send(ARRIVED_PATTERN)
                    current_action = "목적지 도착 진동"
                    print("목적지 도착")
                elif command.kind is CommandKind.TURN and command.angle_degrees is not None:
                    side_distance = left_mm if command.angle_degrees < 0 else right_mm
                    if side_distance is None or side_distance <= cfg.side_blocked_mm:
                        side = Side.LEFT if command.angle_degrees < 0 else Side.RIGHT
                        await wrists.send(PulsePattern(side, (150, 150, 150), (100, 100), 255))
                        current_action = "지도 회전 방향 장애물 · 회전 취소"
                        print("회전 방향이 막혀 지도 회전을 취소했습니다.")
                    else:
                        publish_action(
                            f"지도 {'좌회전' if command.angle_degrees < 0 else '우회전'} "
                            f"{abs(command.angle_degrees):.1f}° 안내"
                        )
                        rotated = await rotation.rotate(command.angle_degrees)
                        if not rotated:
                            await wrists.send(ROTATION_FAILED_PATTERN)
                            current_action = "지도 회전 10초 타임아웃"
                            print("지도 목표각 10초 타임아웃")
                        else:
                            current_action = "지도 회전 완료 · 직진"
                            print(f"지도 회전 완료: {command.angle_degrees:+.1f}°")

            await asyncio.sleep(cfg.loop_interval_seconds)
    finally:
        await wrists.stop()
        await wrists.close()
        rig.close()
    if imu_bus is not None:
            imu_bus.close()


async def run_map_only(args: argparse.Namespace) -> None:
    """Demo gateway: receive clicked map steps and vibrate real wrists only."""

    wrists = BleWristController(simulate=args.simulate_ble)
    api = MapApi(args.server_url)
    pending_navigation = deque()
    last_poll = 0.0
    print("WayBand 지도 전용 모드 시작. 지도 안내 항목을 클릭하세요.")
    try:
        while True:
            now = time.monotonic()
            if not args.obstacle_only and now - last_poll >= 0.4:
                last_poll = now
                try:
                    pending_navigation.extend(await asyncio.to_thread(api.poll))
                except (URLError, TimeoutError, OSError) as exc:
                    print(f"지도 서버 대기: {exc}")

            if pending_navigation:
                command = pending_navigation.popleft()
                if command.kind is CommandKind.TURN and command.angle_degrees is not None:
                    side = Side.LEFT if command.angle_degrees < 0 else Side.RIGHT
                    await wrists.send(PulsePattern(side, (800,), intensity=220))
                    print(f"지도 {('좌회전' if side is Side.LEFT else '우회전')} 진동 전송")
                elif command.kind is CommandKind.CROSSWALK:
                    await wrists.send(CROSSWALK_PATTERN)
                    print("횡단보도 진동 전송")
                elif command.kind is CommandKind.STAIRS:
                    await wrists.send(STAIRS_PATTERN)
                    print("계단 진동 전송")
                elif command.kind is CommandKind.ARRIVED:
                    await wrists.send(ARRIVED_PATTERN)
                    print("도착 진동 전송")
            await asyncio.sleep(0.05)
    finally:
        dashboard_stop.set()
        if dashboard_thread is not None:
            dashboard_thread.join(timeout=1)
        await wrists.stop()
        await wrists.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WayBand 카카오 길안내 + 8x8 ToF + IMU 실전 제어기")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument("--baseline-down-mm", type=int, default=700)
    parser.add_argument("--invert-imu", action="store_true")
    parser.add_argument("--simulate-sensors", action="store_true")
    parser.add_argument("--simulate-ble", action="store_true")
    parser.add_argument("--simulate-imu", action="store_true")
    parser.add_argument("--map-only", action="store_true", help="센서 없이 지도 클릭 햅틱만 실행")
    parser.add_argument("--obstacle-only", action="store_true", help="지도 없이 ToF 장애물 감지와 회피만 실행")
    parser.add_argument("--skip-front", action="store_true", help="전방 VL53L5CX(CH0) 없이 실행")
    parser.add_argument("--terminal", action="store_true", help="ToF 8x8, IMU, 판정과 현재 동작을 터미널에 표시")
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        print("\n안전 정지 완료")
