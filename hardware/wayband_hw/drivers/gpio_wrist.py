"""GPIO(라즈베리파이 직결 모터)로 손목 진동을 구동하는 SerialWristController 대체품.

SerialWristController와 같은 인터페이스(send/stop/close)를 구현해서, main.py는
`--wrist-output ble|gpio` 하나로 둘을 바꿔 끼울 수 있다. gpiozero는 실제로 GPIO를
쓸 때만 임포트한다 — GPIO가 없는 개발 PC에서도 이 모듈을 임포트·테스트할 수 있어야
한다(belt/motors.py와 같은 이유).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from ..core.events import Side
from ..core.patterns import PulsePattern


class Motor(Protocol):
    def on(self, intensity: float) -> None: ...
    def off(self) -> None: ...


class GpioMotor:
    """gpiozero.PWMOutputDevice로 구동되는 실제 진동 모터.

    배선: GPIO(BCM) -> 저항 -> 모터 드라이버 트랜지스터/MOSFET 베이스(게이트) ->
    모터(+플라이백 다이오드) -> GND. intensity(0~1)를 PWM 듀티비로 그대로 쓴다.
    """

    def __init__(self, bcm_pin: int) -> None:
        from gpiozero import PWMOutputDevice

        self._device = PWMOutputDevice(bcm_pin, initial_value=0.0)

    def on(self, intensity: float) -> None:
        self._device.value = max(0.0, min(1.0, intensity))

    def off(self) -> None:
        self._device.value = 0.0


class NullMotor:
    """배선 전 확인·유닛 테스트용 가짜 모터 — 호출 기록만 남기고 아무것도 하지 않는다."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, float]] = []

    def on(self, intensity: float) -> None:
        self.calls.append(("on", intensity))

    def off(self) -> None:
        self.calls.append(("off", 0.0))


@dataclass(slots=True)
class GpioWristController:
    """PulsePattern을 GPIO 모터 펄스로 그대로 재생한다.

    pulses_ms/gaps_ms는 균일하지 않을 수 있다(예: 계단 패턴은 짧은 펄스 뒤 긴 펄스가
    섞여 있다) — belt/pattern_player.py의 균일 on/off 가정을 재사용하지 않고,
    인덱스별로 pulses_ms[i]/gaps_ms[i] 쌍을 그대로 순서대로 재생한다.
    intensity는 PulsePattern이 0-255 정수, PWM 듀티는 0.0-1.0이라 255로 정규화한다.

    send()는 재생이 끝날 때까지 기다리지 않고 백그라운드 태스크로 돌린다 —
    SerialWristController.send()가 ESP32에 명령만 전달하고 바로 반환하는 것과 같은
    타이밍이어야 한다. RotationController.rotate()는 "긴 펄스 하나를 보내놓고
    그동안 IMU로 실제 회전량을 재다가 목표 각도에 도달하면 stop()으로 끊는" 방식으로
    동작하는데, send()가 펄스가 끝날 때까지 블로킹하면 IMU 측정 루프가 펄스 재생이
    다 끝난 뒤에야 시작돼 "목표각 도달 시 정지"가 전혀 동작하지 않는다.
    """

    left_pin: int = 17
    right_pin: int = 27
    simulate: bool = False
    motors: dict[Side, Motor] = field(default_factory=dict, init=False, repr=False)
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.simulate:
            self.motors = {Side.LEFT: NullMotor("LEFT_WRIST"), Side.RIGHT: NullMotor("RIGHT_WRIST")}
        else:
            self.motors = {
                Side.LEFT: GpioMotor(self.left_pin),
                Side.RIGHT: GpioMotor(self.right_pin),
            }

    async def connect(self, side: Side) -> None:
        return None

    def _motors_for(self, side: Side) -> tuple[Motor, ...]:
        if side is Side.BOTH:
            return (self.motors[Side.LEFT], self.motors[Side.RIGHT])
        return (self.motors[side],)

    async def send(self, pattern: PulsePattern) -> None:
        # 이전에 재생 중이던 패턴이 있으면(예: 회전 명령 도중 새 명령이 온 경우)
        # 먼저 끊는다 — 같은 모터를 두 태스크가 동시에 건드리지 않도록.
        await self.stop()
        self._task = asyncio.create_task(self._play(pattern))

    async def _play(self, pattern: PulsePattern) -> None:
        motors = self._motors_for(pattern.side)
        intensity = max(0.0, min(1.0, pattern.intensity / 255.0))
        last_index = len(pattern.pulses_ms) - 1
        try:
            for index, on_ms in enumerate(pattern.pulses_ms):
                for motor in motors:
                    motor.on(intensity)
                await asyncio.sleep(on_ms / 1000)
                # 마지막 펄스의 off는 finally에서 한 번만 낸다 — 취소돼도(목표각 조기
                # 도달 등) 정상 완주해도 항상 같은 경로로 모터를 끈다.
                if index < last_index:
                    for motor in motors:
                        motor.off()
                    if index < len(pattern.gaps_ms):
                        await asyncio.sleep(pattern.gaps_ms[index] / 1000)
        finally:
            for motor in motors:
                motor.off()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for motor in self.motors.values():
            motor.off()

    async def close(self) -> None:
        await self.stop()
