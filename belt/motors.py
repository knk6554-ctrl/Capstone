"""GPIO 모터 구동 계층.

gpiozero는 GpioMotor를 실제로 생성할 때만 임포트한다 — 그래야 이 모듈(과 이를 쓰는
pattern_player)을 GPIO가 없는 개발 PC에서도 임포트/테스트할 수 있다.
"""

from __future__ import annotations

from typing import Protocol


class Motor(Protocol):
    def on(self, intensity: float) -> None: ...
    def off(self) -> None: ...


class GpioMotor:
    """gpiozero.PWMOutputDevice로 구동되는 실제 진동 모터.

    배선: GPIO(BCM) → 저항 → 모터 드라이버 트랜지스터/MOSFET 베이스(게이트) →
    모터(+플라이백 다이오드) → GND. intensity(0~1)를 PWM 듀티비로 그대로 쓴다.
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
