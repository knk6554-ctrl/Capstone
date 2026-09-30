"""회전 시점(TURN_NOW)에서 목표 각도만큼 실제로 돌 때까지 진동을 유지하는 로직.

GPS 거리만으로는 "안내는 했지만 사용자가 실제로 돌았는지"를 알 수 없다. 그래서
TURN_NOW에서는 정해진 횟수만 진동하고 끝내는 대신, 벨트의 IMU로 실제 회전량을
적분해서 목표 각도(HapticCommand.targetAngleDegrees)에 도달할 때까지 진동을 유지하고,
도달하면 바로 멈춘다.

8초(TIMEOUT_SECONDS) 안에 도달하지 못하면 — 실제로 안 돌았든, 센서 오차든 — 그냥
진동을 멈추고 포기한다. 다음 안내(다음 회전·횡단보도 등)는 GPS 기준으로 이미
독립적으로 계속 진행되므로, 여기서 재시도하거나 대체 패턴을 재생하지 않는다
(계속 진동을 붙잡고 있는 쪽이 더 위험하다는 판단 — 모터 소음·배터리·사용자 혼란).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .imu import Imu
from .motors import Motor

TIMEOUT_SECONDS = 8.0
# 목표 각도의 이 오차 안에 들어오면 "다 돌았다"고 본다 — 걸으면서 도는 동작이라
# 정확히 0으로 수렴하길 기대하기 어렵다.
ANGLE_TOLERANCE_DEGREES = 8.0


@dataclass(frozen=True, slots=True)
class TurnResult:
    completed: bool
    rotated_degrees: float
    elapsed_seconds: float


def play_turn(
    *,
    motors: list[Motor],
    imu: Imu,
    intensity: float,
    target_angle_degrees: float,
    pulse_on_ms: int,
    pulse_off_ms: int,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> TurnResult:
    """목표 각도에 도달하거나 타임아웃될 때까지 motors를 pulse_on/off 리듬으로 반복 진동시킨다.

    각속도 적분은 실제 경과 시간이 아니라 pulse_on_ms/pulse_off_ms 명목 값을 쓴다 —
    sleep이 실제로 그만큼 잔다고 신뢰하는 편이 테스트도 결정적이고 코드도 단순하다.
    """

    if not motors or target_angle_degrees == 0 or pulse_on_ms <= 0:
        return TurnResult(completed=False, rotated_degrees=0.0, elapsed_seconds=0.0)

    target = abs(target_angle_degrees)
    on_seconds = pulse_on_ms / 1000
    off_seconds = pulse_off_ms / 1000
    start = now()
    deadline = start + TIMEOUT_SECONDS
    rotated = 0.0

    try:
        while now() < deadline and abs(rotated) < target - ANGLE_TOLERANCE_DEGREES:
            for motor in motors:
                motor.on(intensity)
            sleep(on_seconds)
            rotated += imu.read_gyro_z_dps() * on_seconds

            for motor in motors:
                motor.off()
            if abs(rotated) >= target - ANGLE_TOLERANCE_DEGREES:
                break
            if off_seconds:
                sleep(off_seconds)
                rotated += imu.read_gyro_z_dps() * off_seconds
    finally:
        for motor in motors:
            motor.off()

    completed = abs(rotated) >= target - ANGLE_TOLERANCE_DEGREES
    return TurnResult(
        completed=completed,
        rotated_degrees=rotated,
        elapsed_seconds=now() - start,
    )
