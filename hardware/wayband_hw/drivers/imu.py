from __future__ import annotations

import time
from dataclasses import dataclass

PWR_MGMT_1 = 0x6B
GYRO_CONFIG = 0x1B
GYRO_ZOUT_H = 0x47
GYRO_SCALE = 131.0


def _signed_word(bus: object, address: int, register: int) -> int:
    high = bus.read_byte_data(address, register)
    low = bus.read_byte_data(address, register + 1)
    value = (high << 8) | low
    return value - 65536 if value >= 32768 else value


@dataclass(slots=True)
class Mpu6050Yaw:
    bus: object
    address: int = 0x68
    invert: bool = False
    bias_dps: float = 0.0
    angle_deg: float = 0.0
    _previous: float = 0.0

    def initialize(self, calibration_samples: int = 500) -> None:
        self.bus.write_byte_data(self.address, PWR_MGMT_1, 0)
        self.bus.write_byte_data(self.address, GYRO_CONFIG, 0)
        time.sleep(0.1)
        self.bias_dps = sum(_signed_word(self.bus, self.address, GYRO_ZOUT_H) for _ in range(calibration_samples)) / calibration_samples / GYRO_SCALE
        self.reset()

    def reset(self) -> None:
        self.angle_deg = 0.0
        self._previous = time.monotonic()

    def update(self) -> tuple[float, float]:
        now = time.monotonic()
        dt = min(now - self._previous, 0.1)
        self._previous = now
        rate = _signed_word(self.bus, self.address, GYRO_ZOUT_H) / GYRO_SCALE - self.bias_dps
        # Public convention: negative=left, positive=right.
        rate *= 1 if self.invert else -1
        if abs(rate) >= 0.7:
            self.angle_deg += rate * dt
        return self.angle_deg, rate

