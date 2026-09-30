"""Shared hardware/runtime support for the four focused WayBand demos."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

HARDWARE_ROOT = Path(__file__).resolve().parents[1]
if str(HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(HARDWARE_ROOT))

from wayband_hw.core.events import EventKind, Side, WaybandEvent
from wayband_hw.core.patterns import PulsePattern, pattern_for
from wayband_hw.drivers.ble_wrist import BleWristController
from wayband_hw.drivers.imu import Mpu6050Yaw

from config import Config
from sensor_dashboard import DemoRig, SharedState, render_terminal
from sensors import TofRig


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server-url", default="https://capstone-2jv4.onrender.com")
    parser.add_argument("--baseline-down-mm", type=int, default=700)
    parser.add_argument("--invert-imu", action="store_true")
    parser.add_argument("--simulate-sensors", action="store_true")
    parser.add_argument("--simulate-ble", action="store_true")
    parser.add_argument("--no-web-dashboard", action="store_true")
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--calibration-frames", type=int, default=8)
    parser.add_argument("--missing-hold-frames", type=int, default=5)
    parser.add_argument("--side-filter-window", type=int, default=5)
    parser.add_argument("--sensor-retry-seconds", type=float, default=30.0)


def virtual_front_from_down(down: list[int | None]) -> list[int | None]:
    """Build a dynamic virtual front grid from the upper half of CH0."""
    if len(down) != 64:
        raise ValueError("CH0 down frame must contain 64 cells")
    lower = list(down[:32])
    upper: list[int | None] = []
    for row, offset_mm in enumerate((600, 450, 300, 150)):
        for value in lower[row * 8:(row + 1) * 8]:
            upper.append(None if value is None else min(4000, value + offset_mm))
    return upper + lower


def valid_values(values: list[int | None]) -> list[int]:
    return [value for value in values if value is not None and 0 < value <= 4000]


def fill_missing_from_history(
    current: list[int | None],
    previous: list[int | None],
    missing_ages: list[int],
    max_hold_frames: int,
) -> tuple[list[int | None], int]:
    """Fill short dropouts only; stale values expire after max_hold_frames."""
    if not (len(current) == len(previous) == len(missing_ages)):
        raise ValueError("sensor history lengths must match")
    result: list[int | None] = []
    filled = 0
    for index, value in enumerate(current):
        valid = value is not None and 0 < value <= 4000
        if valid:
            previous[index] = value
            missing_ages[index] = 0
            result.append(value)
        else:
            missing_ages[index] += 1
            cached = previous[index]
            if cached is not None and missing_ages[index] <= max_hold_frames:
                result.append(cached)
                filled += 1
            else:
                result.append(None)
    return result, filled


def virtual_front_blocked(front: list[int | None], limit_mm: int) -> bool:
    lower = valid_values(front[32:])
    return len(lower) >= 8 and sum(value <= limit_mm for value in lower) >= 6


def _grid(values: list[int | None]) -> list[list[int | None]]:
    return [values[row * 8:(row + 1) * 8] for row in range(8)]


def _web_payload(payload: dict[str, Any]) -> dict[str, Any]:
    angle = float(payload["angle_deg"])
    direction = "LEFT" if angle < -0.5 else "RIGHT" if angle > 0.5 else "NONE"
    return {
        "stats": {
            "leftSideMm": payload["left_mm"],
            "rightSideMm": payload["right_mm"],
            "rotationDeg": angle,
            "gyroZOffsetDegPerSec": payload["imu_bias_dps"],
            "gyroZFinalDegPerSec": payload["rate_dps"],
        },
        "imu": {"direction": direction, "angleDeg": angle},
        "tof": {
            "front": _grid(payload["front"]),
            "down": _grid(payload["down"]),
            "frontLabel": payload.get("front_label", "전방 ToF 8×8"),
        },
        "decisions": [
            {"label": "장애물", "value": payload["obstacle"]},
            {"label": "계단/낙차", "value": payload["stairs"]},
            {"label": "회피 결정", "value": payload["avoidance"]},
            {"label": "팔찌 진동", "value": payload["haptic_status"]},
        ],
    }


def _push(server_url: str, payload: dict[str, Any]) -> None:
    request = Request(
        f"{server_url.rstrip('/')}/api/sensors/dashboard",
        data=json.dumps(_web_payload(payload)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2):
        pass


class DemoRuntime:
    def __init__(self, args: argparse.Namespace, name: str):
        self.args = args
        self.name = name
        self.cfg = Config(
            server_url=args.server_url,
            baseline_down_mm=args.baseline_down_mm,
            imu_invert=args.invert_imu,
            enable_front=False,
        )
        self.rig: Any = DemoRig(self.cfg) if args.simulate_sensors else TofRig(self.cfg)
        self.wrists = BleWristController(simulate=args.simulate_ble)
        self.bus = None
        self.imu: Mpu6050Yaw | None = None
        self.state = SharedState({"error": "센서 초기화 중입니다."})
        self.last_push = 0.0
        self.web_status = "아직 전송 안 함"
        self.last_haptic: dict[str, float] = {}
        self.running = True
        self.previous_down: list[int | None] = [None] * 64
        self.down_missing_ages = [0] * 64
        window = max(1, args.side_filter_window)
        self.side_history = {"left": deque(maxlen=window), "right": deque(maxlen=window)}
        self.side_missing = {"left": 0, "right": 0}
        self.sensor_seen = {"down": False, "left": False, "right": False}
        self.sensor_failures = {"down": 0, "left": 0, "right": 0}
        self.last_sensor_retry = -1e9
        self.sensor_recovery_status = "재연결 대기 없음"

    async def start(self) -> None:
        self.rig.start()
        if not self.args.simulate_sensors:
            await self._calibrate_down()
            from smbus2 import SMBus

            self.bus = SMBus(self.cfg.i2c_bus)
            self.imu = Mpu6050Yaw(self.bus, self.cfg.imu_address, self.cfg.imu_invert)
            print("IMU 보정 중입니다. 장치를 움직이지 마세요.")
            await asyncio.to_thread(self.imu.initialize)

    async def _calibrate_down(self) -> None:
        frame_values: list[int] = []
        frames = max(1, self.args.calibration_frames)
        print(f"하향 센서 평지 보정 중입니다 ({frames}프레임). 장치를 움직이지 마세요.")
        for index in range(frames):
            _front, down, _left, _right = await asyncio.to_thread(self.rig.snapshot)
            roi = [down[row * 8 + column] for row in range(4, 8) for column in range(1, 7)]
            values = valid_values(roi)
            if values:
                frame_values.append(round(statistics.median(values)))
            print(f"\r하향 센서 보정 {index + 1}/{frames}", end="", flush=True)
        print()
        if frame_values:
            baseline = round(statistics.median(frame_values))
            self.cfg = replace(self.cfg, baseline_down_mm=baseline)
            self.sensor_recovery_status = f"평지 기준 {baseline}mm 자동 보정"
        else:
            self.sensor_recovery_status = f"자동 보정 실패 · 설정값 {self.cfg.baseline_down_mm}mm 사용"

    def _smooth_side(self, name: str, value: int | None) -> tuple[int | None, bool]:
        history = self.side_history[name]
        if value is not None and 0 < value <= 4000:
            history.append(value)
            self.side_missing[name] = 0
            return round(statistics.median(history)), False
        self.side_missing[name] += 1
        if history and self.side_missing[name] <= self.args.missing_hold_frames:
            return round(statistics.median(history)), True
        return None, False

    async def _track_and_recover(
        self,
        raw_down: list[int | None],
        raw_left: int | None,
        raw_right: int | None,
    ) -> None:
        available = {
            "down": bool(valid_values(raw_down)),
            "left": raw_left is not None and 0 < raw_left <= 4000,
            "right": raw_right is not None and 0 < raw_right <= 4000,
        }
        for name, ok in available.items():
            self.sensor_seen[name] = self.sensor_seen[name] or ok
            self.sensor_failures[name] = 0 if ok else self.sensor_failures[name] + 1
        failed = [name for name in available if self.sensor_seen[name] and self.sensor_failures[name] >= 5]
        now = time.monotonic()
        if self.args.simulate_sensors or not failed or now - self.last_sensor_retry < self.args.sensor_retry_seconds:
            return
        self.last_sensor_retry = now
        self.sensor_recovery_status = f"재연결 시도: {', '.join(failed)}"
        try:
            await asyncio.to_thread(self.rig.close)
            replacement = TofRig(self.cfg)
            await asyncio.to_thread(replacement.start)
            self.rig = replacement
            self.sensor_recovery_status = "센서 재연결 완료"
            for name in failed:
                self.sensor_failures[name] = 0
        except Exception as exc:
            self.sensor_recovery_status = f"센서 재연결 실패: {exc}"

    async def close(self) -> None:
        self.running = False
        try:
            await self.wrists.stop()
        finally:
            await self.wrists.close()
            self.rig.close()
            if self.bus is not None:
                self.bus.close()

    def reset_angle(self) -> None:
        if self.imu is not None:
            self.imu.reset()

    async def haptic(self, key: str, pattern: PulsePattern, cooldown: float = 1.0) -> bool:
        now = time.monotonic()
        if now - self.last_haptic.get(key, -1e9) < cooldown:
            return False
        await self.wrists.send(pattern)
        self.last_haptic[key] = now
        return True

    async def event_haptic(self, event: WaybandEvent, cooldown: float | None = None) -> bool:
        pattern = pattern_for(event)
        wait = cooldown if cooldown is not None else max(1.0, pattern.repeat_after_ms / 1000.0)
        return await self.haptic(event.kind.value, pattern, wait)

    async def sample(
        self,
        stage: str,
        *,
        obstacle: str = "장애물 없음",
        stairs: str = "계단 없음",
        avoidance: str = "직진 가능",
        avoidance_angle: float | None = 0.0,
    ) -> dict[str, Any]:
        if self.args.simulate_sensors:
            _unused_front, down, left, right, angle, rate, _source = self.rig.snapshot()
        else:
            _unused_front, raw_down, raw_left, raw_right = await asyncio.to_thread(self.rig.snapshot)
            angle, rate = self.imu.update() if self.imu is not None else (0.0, 0.0)

        if self.args.simulate_sensors:
            raw_down, raw_left, raw_right = down, left, right
        await self._track_and_recover(raw_down, raw_left, raw_right)
        raw_valid_cells = len(valid_values(raw_down))
        down, down_filled = fill_missing_from_history(
            raw_down, self.previous_down, self.down_missing_ages, self.args.missing_hold_frames
        )
        left, left_filled = self._smooth_side("left", raw_left)
        right, right_filled = self._smooth_side("right", raw_right)

        front = virtual_front_from_down(down)
        statuses = {
            "하향 CH0": (
                f"정상 {raw_valid_cells}/64셀"
                + (f" · 이전값 보정 {down_filled}셀" if down_filled else "")
                if valid_values(down) else "측정 불가"
            ),
            "가상 전방": "CH0 기반 동적 시연값",
            "좌측 CH2": "이전값 보정" if left_filled else "정상" if left is not None else "측정 불가",
            "우측 CH3": "이전값 보정" if right_filled else "정상" if right is not None else "측정 불가",
            "IMU": "정상" if self.imu is not None or self.args.simulate_sensors else "측정 불가",
        }
        levels = ["normal", "normal", "normal", "normal"]
        if obstacle != "장애물 없음":
            levels[0] = "danger"
        if stairs != "계단 없음":
            levels[1] = "danger" if "낙차" in stairs else "warning"
        if left is not None and left <= self.cfg.side_clear_mm:
            levels[2] = "warning"
        if right is not None and right <= self.cfg.side_clear_mm:
            levels[3] = "warning"

        payload = {
            "timestamp": time.time(),
            "source": f"{self.name} · 실제 센서" if not self.args.simulate_sensors else f"{self.name} · 모의 센서",
            "front": front,
            "front_enabled": True,
            "front_label": "가상 전방 8×8 · CH0 기반 시연값",
            "down": down,
            "front_nearest_mm": min(valid_values(front), default=None),
            "down_median_mm": round(statistics.median(valid_values(down))) if valid_values(down) else None,
            "down_raw_valid_cells": raw_valid_cells,
            "down_filled_cells": down_filled,
            "left_mm": left,
            "right_mm": right,
            "angle_deg": round(angle, 1),
            "rate_dps": round(rate, 1),
            "imu_bias_dps": round(self.imu.bias_dps if self.imu is not None else 0.0, 2),
            "obstacle": obstacle,
            "stairs": stairs,
            "avoidance": avoidance,
            "avoidance_angle_deg": avoidance_angle,
            "levels": levels,
            "counts": {name: levels.count(name) for name in ("normal", "warning", "danger")},
            "demo_stage": stage,
            "sensor_status": statuses,
            "haptic_status": self.wrists.status_text(),
            "web_dashboard_status": self.web_status,
        }

        now = time.monotonic()
        if not self.args.no_web_dashboard and now - self.last_push >= 0.5:
            self.last_push = now
            try:
                await asyncio.to_thread(_push, self.args.server_url, payload)
                self.web_status = f"정상 전송 ({time.strftime('%H:%M:%S')})"
            except (URLError, TimeoutError, OSError) as exc:
                self.web_status = f"전송 실패: {exc}"
            payload["web_dashboard_status"] = self.web_status

        self.state.set(payload)
        status_line = " / ".join(f"{key}:{value}" for key, value in statuses.items())
        extra = (
            f"\n[시연 단계] {stage}"
            f"\n[센서 연결] {status_line}"
            f"\n[BLE 연결] {self.wrists.status_text()}"
            f"\n[센서 복구] {self.sensor_recovery_status}"
            f"\n[웹 대시보드] {self.web_status}"
        )
        print("\033[2J\033[H" + render_terminal(payload) + extra, end="", flush=True)
        return payload

    async def wait_with_sensors(self, seconds: float, stage: str, **labels: Any) -> None:
        deadline = time.monotonic() + seconds
        while self.running and time.monotonic() < deadline:
            await self.sample(stage, **labels)
            await asyncio.sleep(self.args.interval)


async def run_safely(runtime: DemoRuntime, body: Any) -> None:
    try:
        await runtime.start()
        await body(runtime)
    finally:
        await runtime.close()


LEFT_TURN_PATTERN = PulsePattern(Side.LEFT, (1000,), intensity=230)
RIGHT_TURN_PATTERN = PulsePattern(Side.RIGHT, (1000,), intensity=230)
CROSSWALK_PATTERN = PulsePattern(Side.BOTH, (500, 500), (300,), 190)
ARRIVAL_PATTERN = PulsePattern(Side.BOTH, (700, 700), (350,), 220)
