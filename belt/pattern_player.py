"""서버가 보낸 HapticCommand(JSON) 하나를 실제 모터 펄스로 재생하는 순수 로직.

GPIO를 직접 건드리지 않아서(Motor 인터페이스 뒤로 감춤) 일반 PC에서도 유닛 테스트할 수
있다. 상황별 "몇 번·몇 ms" 숫자는 여기서 다시 정의하지 않는다 — wayband/navigation.py,
wayband/hazard.py가 만든 pulseCount/pulseOnMs/pulseOffMs/intensity를 그대로 재생만
한다(README.md "진동 의미" 표 참고). 그래야 서버 쪽 값이 바뀌어도 벨트 코드를 다시
배포하지 않아도 된다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .imu import Imu
from .motors import Motor
from .turn_tracker import TurnResult, play_turn

# target(JSON 문자열) -> 실제로 울릴 물리 모터 이름들. BOTH_WRISTS만 모터 두 개를 동시에 쓴다.
TARGET_MOTORS: dict[str, tuple[str, ...]] = {
    "LEFT_WRIST": ("LEFT_WRIST",),
    "RIGHT_WRIST": ("RIGHT_WRIST",),
    "BOTH_WRISTS": ("LEFT_WRIST", "RIGHT_WRIST"),
    "BELT_FRONT_LEFT": ("BELT_FRONT_LEFT",),
    "BELT_FRONT_RIGHT": ("BELT_FRONT_RIGHT",),
    "BELT_LEFT_SIDE": ("BELT_LEFT_SIDE",),
    "BELT_RIGHT_SIDE": ("BELT_RIGHT_SIDE",),
}

# 서버 값이 정상 범위(가장 긴 패턴도 700ms/5회)를 크게 벗어나 모터가 눌어붙는 걸 막는
# 안전 상한. 정상 동작에서는 절대 걸리지 않는다.
MAX_PULSE_ON_MS = 2000
MAX_PULSE_COUNT = 20


@dataclass(frozen=True, slots=True)
class Pulse:
    """한 번의 on(+뒤이은 off) 구간. 마지막 펄스는 off가 없다(0)."""

    on_ms: int
    off_ms: int


def build_pulse_plan(
    pulse_count: int, pulse_on_ms: int, pulse_off_ms: int
) -> tuple[Pulse, ...]:
    count = max(0, min(pulse_count, MAX_PULSE_COUNT))
    on_ms = max(0, min(pulse_on_ms, MAX_PULSE_ON_MS))
    off_ms = max(0, min(pulse_off_ms, MAX_PULSE_ON_MS))
    if count == 0 or on_ms == 0:
        return ()
    return tuple(
        Pulse(on_ms=on_ms, off_ms=off_ms if i < count - 1 else 0)
        for i in range(count)
    )


def motors_for_target(target: str) -> tuple[str, ...]:
    try:
        return TARGET_MOTORS[target]
    except KeyError as exc:
        raise ValueError(f"알 수 없는 target입니다: {target}") from exc


class PatternPlayer:
    """모터 맵을 들고 있다가 HapticCommand 딕셔너리를 하나씩 재생한다."""

    def __init__(
        self,
        motors: dict[str, Motor],
        *,
        imu: Imu | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._motors = motors
        self._imu = imu
        self._sleep = sleep
        self._now = now

    def play(self, command: dict) -> None:
        motor_names = motors_for_target(command["target"])
        motors = [self._motors[name] for name in motor_names if name in self._motors]
        if not motors:
            return

        intensity = max(0.0, min(1.0, float(command["intensity"])))
        plan = build_pulse_plan(
            int(command["pulseCount"]),
            int(command["pulseOnMs"]),
            int(command["pulseOffMs"]),
        )
        for pulse in plan:
            for motor in motors:
                motor.on(intensity)
            self._sleep(pulse.on_ms / 1000)
            for motor in motors:
                motor.off()
            if pulse.off_ms:
                self._sleep(pulse.off_ms / 1000)

    def can_play_turn(self, command: dict) -> bool:
        """이 명령이 IMU 각도 추적(continuous) 방식으로 재생 가능한지.

        TURN_NOW이고 서버가 목표 각도를 보냈고(PREPARE_TURN은 아직 각도를 볼 필요가
        없다) IMU가 실제로 연결돼 있을 때만 True. 그 외에는 호출자가 play()로
        고정 펄스를 재생해야 한다(IMU 미배선 시의 안전한 폴백).
        """

        return (
            self._imu is not None
            and command.get("pattern") == "TURN_NOW"
            and command.get("targetAngleDegrees") is not None
        )

    def play_turn_command(self, command: dict) -> TurnResult:
        motor_names = motors_for_target(command["target"])
        motors = [self._motors[name] for name in motor_names if name in self._motors]
        assert self._imu is not None  # can_play_turn()으로 미리 확인했다고 가정

        return play_turn(
            motors=motors,
            imu=self._imu,
            intensity=max(0.0, min(1.0, float(command["intensity"]))),
            target_angle_degrees=float(command["targetAngleDegrees"]),
            pulse_on_ms=int(command["pulseOnMs"]),
            pulse_off_ms=int(command["pulseOffMs"]),
            sleep=self._sleep,
            now=self._now,
        )
