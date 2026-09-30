"""독립 시연용: 직진 → 전방 장애물 감지 → 좌측 확인(막힘) → 우측 확인(열림) → 우회전.

hardware/real/main.py의 전체 제어 루프(지도 연동·계단/낙차 판정·IMU 회전 추적 등)와는
별개로, 이 시나리오 하나만 빠르고 확실하게 보여주기 위한 최소 의존성 스크립트다.
main.py에는 아직 통합하지 않았다 — 이 데모 로직이 검증되면 통합 여부를 따로 정한다.

의사결정 로직(decide_next_step)은 순수 함수라 실제 센서·팔찌 없이 유닛 테스트할 수 있다.

실행:
    python3 demo_obstacle_avoidance.py --simulate-sensors --simulate-ble
        하드웨어 없이 시나리오만 반복 확인(3초 직진 후 장애물 등장, 좌측 막힘, 우측 열림).
    python3 demo_obstacle_avoidance.py --wrist-output ble
        실제 ToF 센서 + BLE 팔찌.
    python3 demo_obstacle_avoidance.py --wrist-output gpio --simulate-ble
        실제 ToF 센서 + 라즈베리파이 GPIO 모터(팔찌 대신).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

HARDWARE_ROOT = Path(__file__).resolve().parents[1]
if str(HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(HARDWARE_ROOT))

from wayband_hw.core.events import Side
from wayband_hw.core.patterns import PulsePattern
from wayband_hw.drivers.ble_wrist import BleWristController
from wayband_hw.drivers.gpio_wrist import GpioWristController

from config import Config
from control import FRONT_WARNING_PATTERN, ROTATION_FAILED_PATTERN, front_is_blocked
from sensors import TofRig

TURN_LEFT_PATTERN = PulsePattern(Side.LEFT, (800,), intensity=220)
TURN_RIGHT_PATTERN = PulsePattern(Side.RIGHT, (800,), intensity=220)


class DemoPhase(str, Enum):
    WALKING = "WALKING"
    CHECKING_LEFT = "CHECKING_LEFT"
    CHECKING_RIGHT = "CHECKING_RIGHT"
    MOVING = "MOVING"
    BLOCKED = "BLOCKED"


class DemoAction(str, Enum):
    NONE = "NONE"
    FRONT_WARNING = "FRONT_WARNING"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    NO_PATH = "NO_PATH"


@dataclass(frozen=True, slots=True)
class DemoStep:
    phase: DemoPhase
    action: DemoAction
    message: str


def decide_next_step(
    phase: DemoPhase,
    *,
    blocked: bool,
    left_mm: int | None,
    right_mm: int | None,
    side_clear_mm: int,
) -> DemoStep:
    """현재 단계 + 이번 센서값으로 다음 단계와 취할 조치를 정한다.

    "왼쪽을 먼저 본다"는 순서를 코드로 고정해둔 것 — 장애물 회피 각도를 점수로
    계산하는 plan_avoidance_angle()과 달리, 이 데모는 항상 좌측부터 확인하고
    막혀 있을 때만 우측을 본다(시연 시나리오와 정확히 일치시키기 위함).
    """

    if phase is DemoPhase.WALKING:
        if blocked:
            return DemoStep(
                DemoPhase.CHECKING_LEFT,
                DemoAction.FRONT_WARNING,
                "전방 장애물 감지 — 정지하고 좌측부터 확인합니다.",
            )
        return DemoStep(DemoPhase.WALKING, DemoAction.NONE, "직진 중")

    if phase is DemoPhase.CHECKING_LEFT:
        if left_mm is None or left_mm >= side_clear_mm:
            return DemoStep(
                DemoPhase.MOVING,
                DemoAction.TURN_LEFT,
                f"좌측 확인: 열림({left_mm}mm) — 좌회전합니다.",
            )
        return DemoStep(
            DemoPhase.CHECKING_RIGHT,
            DemoAction.NONE,
            f"좌측 확인: 막힘({left_mm}mm) — 우측을 확인합니다.",
        )

    if phase is DemoPhase.CHECKING_RIGHT:
        if right_mm is None or right_mm >= side_clear_mm:
            return DemoStep(
                DemoPhase.MOVING,
                DemoAction.TURN_RIGHT,
                f"우측 확인: 열림({right_mm}mm) — 우회전합니다.",
            )
        return DemoStep(
            DemoPhase.BLOCKED,
            DemoAction.NO_PATH,
            "우측도 막힘 — 안전한 통로가 없어 정지합니다.",
        )

    # MOVING·BLOCKED — 데모의 마지막 단계, 더 이상 상태가 바뀌지 않는다.
    return DemoStep(phase, DemoAction.NONE, "")


class DemoScenarioRig:
    """'직진 → 전방 장애물 → 좌측 막힘 → 우측 열림' 시나리오를 그대로 재생하는 가짜 센서.

    실제 하드웨어 없이도 시연 흐름을 몇 번이고 똑같이 반복 확인하려고 만들었다 —
    TofRig와 같은 snapshot() 모양(front, down, left_mm, right_mm)을 그대로 흉내낸다.
    """

    def __init__(self, cfg: Config, *, obstacle_after_seconds: float = 3.0) -> None:
        self.cfg = cfg
        self.obstacle_after_seconds = obstacle_after_seconds
        self._started = 0.0

    def start(self) -> None:
        self._started = time.monotonic()

    def snapshot(self):
        elapsed = time.monotonic() - self._started
        front = [1800] * 64
        down = [self.cfg.baseline_down_mm] * 64
        left_mm, right_mm = 1800, 1800

        if elapsed >= self.obstacle_after_seconds:
            # 전방 중앙에 장애물, 좌측은 막힘, 우측은 열려 있다.
            for row in range(2, 7):
                for col in range(2, 6):
                    front[row * 8 + col] = 350
            left_mm = 400

        return front, down, left_mm, right_mm

    def close(self) -> None:
        return None


def _build_wrists(args: argparse.Namespace, cfg: Config):
    """--wrist-output에 따라 BleWristController 또는 GpioWristController를 만든다."""

    if args.wrist_output == "gpio":
        return GpioWristController(
            cfg.left_wrist_pin, cfg.right_wrist_pin, simulate=args.simulate_ble
        )
    return BleWristController(simulate=args.simulate_ble)


async def run_demo(args: argparse.Namespace) -> None:
    cfg = Config(enable_front=True)
    rig = DemoScenarioRig(cfg) if args.simulate_sensors else TofRig(cfg)
    wrists = _build_wrists(args, cfg)

    rig.start()
    phase = DemoPhase.WALKING
    print("시연 시작 — 직진 중... (Ctrl+C로 중단)")
    try:
        while phase not in (DemoPhase.MOVING, DemoPhase.BLOCKED):
            front, down, left_mm, right_mm = await asyncio.to_thread(rig.snapshot)
            blocked = front_is_blocked(front, cfg.front_warning_mm)

            step = decide_next_step(
                phase,
                blocked=blocked,
                left_mm=left_mm,
                right_mm=right_mm,
                side_clear_mm=cfg.side_clear_mm,
            )
            if step.message and step.phase is not phase:
                print(step.message)

            if step.action is DemoAction.FRONT_WARNING:
                await wrists.send(FRONT_WARNING_PATTERN)
            elif step.action is DemoAction.TURN_LEFT:
                await wrists.send(TURN_LEFT_PATTERN)
            elif step.action is DemoAction.TURN_RIGHT:
                await wrists.send(TURN_RIGHT_PATTERN)
            elif step.action is DemoAction.NO_PATH:
                await wrists.send(ROTATION_FAILED_PATTERN)

            phase = step.phase
            await asyncio.sleep(cfg.loop_interval_seconds)

        if phase is DemoPhase.MOVING:
            print("회피 방향으로 전진합니다 — 시연 종료.")
        else:
            print("시연 종료 — 안전한 통로를 찾지 못했습니다.")
    finally:
        await wrists.stop()
        await wrists.close()
        rig.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WayBand 독립 시연: 직진 중 전방 장애물 감지 → 좌측 확인 → 우측 확인 → 회피"
    )
    parser.add_argument(
        "--simulate-sensors",
        action="store_true",
        help="실제 ToF 없이 정해둔 시나리오(3초 직진 후 전방 장애물·좌측 막힘·우측 열림) 재생",
    )
    parser.add_argument("--simulate-ble", action="store_true", help="실제 팔찌/모터 없이 진동 전송 시험")
    parser.add_argument(
        "--wrist-output",
        choices=("ble", "gpio"),
        default="ble",
        help="손목 진동 출력 방식 (기본 ble)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run_demo(args))
    except KeyboardInterrupt:
        print("\n안전 정지 완료")
