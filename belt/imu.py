"""IMU(자이로) 추상화 — 실제로 어떤 IMU 칩을 쓸지 정해지면 RealImu 내부만 바꾸면 된다.

turn_tracker.py가 필요한 건 Z축(수직축, 몸이 좌우로 도는 축) 각속도 하나뿐이다.
부호 규약은 서버의 targetAngleDegrees(route_parser.turn_angle_degrees)와 맞춘다:
위에서 내려다봤을 때 시계방향(=우회전 방향)이 양수, 반시계방향(=좌회전)이 음수.
실제 센서 장착 방향에 따라 부호가 반대일 수 있으니 배선 후 실측으로 확인해야 한다.
"""

from __future__ import annotations

from typing import Protocol


class Imu(Protocol):
    def read_gyro_z_dps(self) -> float:
        """Z축 각속도(도/초). 시계방향(우회전 방향)이 양수."""
        ...


class RealImu:
    """MPU6050류 IMU에서 자이로 Z값을 읽는다 (I2C).

    실제로 쓸 IMU 모델/라이브러리가 정해지면 이 클래스 내부(임포트, read_gyro_z_dps
    구현)만 바꾸면 된다 — 다른 코드는 Imu 프로토콜만 알면 되므로 영향받지 않는다.
    """

    def __init__(self, i2c_bus: int = 1, address: int = 0x68) -> None:
        from mpu6050 import mpu6050  # pip install mpu6050-raspberrypi

        self._sensor = mpu6050(address, bus=i2c_bus)

    def read_gyro_z_dps(self) -> float:
        return float(self._sensor.get_gyro_data()["z"])


class ScriptedImu:
    """배선 전 확인·유닛 테스트용 — 정해둔 각속도 값을 순서대로 돌려주다가 마지막 값을 유지한다."""

    def __init__(self, readings: list[float]) -> None:
        if not readings:
            raise ValueError("readings는 최소 1개 이상이어야 합니다.")
        self._readings = list(readings)
        self._index = 0

    def read_gyro_z_dps(self) -> float:
        value = self._readings[min(self._index, len(self._readings) - 1)]
        self._index += 1
        return value
