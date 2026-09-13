"""Read two VL53L5CX and two VL53L1X sensors through a TCA9548A."""

from __future__ import annotations

import argparse
import math
import sys
import time
from math import isqrt

from test_utils import AUTO_CSV, CsvLogger, csv_path

I2C_BUS = 1
TCA9548A_ADDRESS = 0x70
SENSOR_ADDRESS = 0x29
RESOLUTION = 8 * 8

L5CX_CHANNELS = {0: "전방", 1: "하향"}
L1X_CHANNELS = {2: "좌측", 3: "우측"}


def select_channel(bus: object, channel: int | None) -> None:
    bus.write_byte(TCA9548A_ADDRESS, 0 if channel is None else 1 << channel)
    time.sleep(0.002)


def valid_distances(values: list[int]) -> list[int]:
    # Project protocol treats 0 and values over 4000 mm as invalid.
    return [value for value in values if 0 < value <= 4000]


def print_grid(values: list[int]) -> None:
    width = isqrt(len(values))
    for row in range(width):
        start = row * width
        print(" ".join(f"{value:4d}" for value in values[start : start + width]))


def initialize_l5cx(bus: object) -> dict[int, object]:
    import qwiic_vl53l5cx

    sensors: dict[int, object] = {}
    for channel, label in L5CX_CHANNELS.items():
        print(f"[{label}] 채널 {channel} 초기화 중 (최대 약 10초)...")
        select_channel(bus, channel)
        sensor = qwiic_vl53l5cx.QwiicVL53L5CX(address=SENSOR_ADDRESS)
        if not sensor.is_connected():
            raise RuntimeError(f"{label}: 채널 {channel}에서 센서 0x29를 찾지 못했습니다.")
        if not sensor.begin():
            raise RuntimeError(f"{label}: VL53L5CX 초기화에 실패했습니다.")
        sensor.set_resolution(RESOLUTION)
        sensor.start_ranging()
        sensors[channel] = sensor
    return sensors


def initialize_l1x(bus: object) -> dict[int, object]:
    import qwiic_vl53l1x

    sensors: dict[int, object] = {}
    for channel, label in L1X_CHANNELS.items():
        print(f"[{label}] 채널 {channel} VL53L1X 초기화 중...")
        sensor = None
        last_result = None
        for attempt in range(1, 4):
            select_channel(bus, None)
            time.sleep(0.1)
            select_channel(bus, channel)
            time.sleep(0.2)
            sensor = qwiic_vl53l1x.QwiicVL53L1X(address=SENSOR_ADDRESS)
            last_result = sensor.sensor_init()
            # SparkFun releases have returned either None or 0 on success.
            if last_result in (None, 0):
                print(f"[{label}] 초기화 성공")
                break
            print(f"[{label}] 초기화 재시도 {attempt}/3, 반환값={last_result!r}")
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"{label}: VL53L1X 초기화 실패, 반환값={last_result!r}"
            )

        assert sensor is not None
        sensors[channel] = sensor
        time.sleep(0.3)
    return sensors


def run_simulation(logger: CsvLogger) -> None:
    print("ToF 모의 측정 시작 (Ctrl+C로 종료, 단위 mm)")
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        front = round(1000 + 450 * math.sin(elapsed * 0.7))
        down = round(520 + 25 * math.sin(elapsed * 0.4))
        left = round(1500 + 500 * math.sin(elapsed * 0.5 + 1.0))
        right = round(1700 + 450 * math.sin(elapsed * 0.6 + 2.0))
        print(f"\r전방={front:4d} 하향={down:4d} 좌측={left:4d} 우측={right:4d} mm   ", end="", flush=True)
        logger.write(mode="simulate", front_nearest_mm=front, down_nearest_mm=down, left_mm=left, right_mm=right)
        time.sleep(0.25)


def run_hardware(logger: CsvLogger) -> None:
    from smbus2 import SMBus

    with SMBus(I2C_BUS) as bus:
        l5cx_sensors = initialize_l5cx(bus)
        l1x_sensors = initialize_l1x(bus)
        print("\n측정 시작 (Ctrl+C로 종료, 단위 mm)")
        while True:
            readings: dict[str, int | None] = {"front": None, "down": None, "left": None, "right": None}
            for channel, label in L5CX_CHANNELS.items():
                select_channel(bus, channel)
                sensor = l5cx_sensors[channel]
                if not sensor.check_data_ready():
                    continue
                values = list(sensor.get_ranging_data().distance_mm)
                usable = valid_distances(values)
                nearest = min(usable) if usable else None
                readings["front" if channel == 0 else "down"] = nearest
                nearest_text = f"{nearest} mm" if nearest is not None else "유효값 없음"
                print(f"\n[{label} / TCA {channel}] 가장 가까운 거리: {nearest_text}")
                print_grid(values)

            for channel, label in L1X_CHANNELS.items():
                select_channel(bus, channel)
                sensor = l1x_sensors[channel]
                sensor.start_ranging()
                time.sleep(0.01)
                distance = sensor.get_distance()
                sensor.stop_ranging()
                value = distance if 0 < distance <= 4000 else None
                readings["left" if channel == 2 else "right"] = value
                distance_text = f"{value} mm" if value is not None else "유효값 없음"
                print(f"[{label} / TCA {channel} / VL53L1X] 거리: {distance_text}")

            logger.write(
                mode="hardware",
                front_nearest_mm=readings["front"],
                down_nearest_mm=readings["down"],
                left_mm=readings["left"],
                right_mm=readings["right"],
            )
            time.sleep(0.01)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="센서 없이 모의 거리값 생성")
    parser.add_argument("--csv", nargs="?", const=AUTO_CSV, help="CSV 저장 경로(생략 시 logs에 자동 생성)")
    args = parser.parse_args()
    fields = ["timestamp", "mode", "front_nearest_mm", "down_nearest_mm", "left_mm", "right_mm"]
    try:
        with CsvLogger(csv_path(args.csv, "tof"), fields) as logger:
            run_simulation(logger) if args.simulate else run_hardware(logger)
    except KeyboardInterrupt:
        print("\n측정을 종료합니다.")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
