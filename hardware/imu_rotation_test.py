"""Measure cumulative left/right yaw rotation with an MPU6050 gyroscope."""

from __future__ import annotations

import argparse
import math
import queue
import sys
import threading
import time

from test_utils import AUTO_CSV, CsvLogger, csv_path

I2C_BUS = 1
MPU6050_ADDRESSES = (0x68, 0x69)
PWR_MGMT_1 = 0x6B
GYRO_CONFIG = 0x1B
GYRO_ZOUT_H = 0x47
GYRO_SCALE_250_DPS = 131.0
CALIBRATION_SAMPLES = 500
DEADBAND_DPS = 0.7
PRINT_INTERVAL_SECONDS = 0.25
CSV_INTERVAL_SECONDS = 0.02


def read_word_signed(bus: object, address: int, register: int) -> int:
    high = bus.read_byte_data(address, register)
    low = bus.read_byte_data(address, register + 1)
    value = (high << 8) | low
    return value - 65536 if value >= 32768 else value


def find_mpu6050(bus: object) -> int:
    for address in MPU6050_ADDRESSES:
        try:
            bus.read_byte_data(address, PWR_MGMT_1)
            return address
        except OSError:
            continue
    raise RuntimeError("MPU6050을 0x68 또는 0x69에서 찾지 못했습니다.")


def calibrate_gyro(bus: object, address: int) -> float:
    print("초기 보정 중입니다. 센서를 움직이지 마세요...")
    total = 0
    for _ in range(CALIBRATION_SAMPLES):
        total += read_word_signed(bus, address, GYRO_ZOUT_H)
        time.sleep(0.002)
    bias = total / CALIBRATION_SAMPLES / GYRO_SCALE_250_DPS
    print(f"보정 완료 (Z축 오프셋 {bias:+.3f} °/s)")
    return bias


def input_worker(commands: queue.Queue[str]) -> None:
    while True:
        try:
            commands.put(input().strip().lower())
        except EOFError:
            commands.put("quit")
            return


def describe_angle(angle: float) -> str:
    if abs(angle) < 0.5:
        return "기준점 0도"
    direction = "왼쪽" if angle > 0 else "오른쪽"
    return f"{direction} {abs(angle):.1f}도"


def simulated_rate(elapsed: float) -> float:
    phase = elapsed % 12.0
    if 1.0 <= phase < 3.0:
        return 15.0  # 2초 동안 왼쪽으로 약 30도
    if 5.0 <= phase < 7.0:
        return -22.5  # 2초 동안 오른쪽으로 약 45도
    return 0.15 * math.sin(elapsed * 2.0)


def run_measurement(read_rate: object, direction_sign: float, logger: CsvLogger, mode: str) -> int:
    commands: queue.Queue[str] = queue.Queue()
    threading.Thread(target=input_worker, args=(commands,), daemon=True).start()
    print("측정 시작: reset=각도 0으로 초기화, quit=종료")
    angle = 0.0
    started = previous = time.monotonic()
    next_print = previous
    next_csv = previous

    while True:
        now = time.monotonic()
        dt = min(now - previous, 0.1)
        previous = now
        rate = read_rate(now - started) * direction_sign
        if abs(rate) >= DEADBAND_DPS:
            angle += rate * dt

        try:
            command = commands.get_nowait()
            if command == "reset":
                angle = 0.0
                print("\n각도 기준을 0도로 초기화했습니다.")
            elif command in {"quit", "q"}:
                print("\n측정을 종료합니다.")
                return 0
            elif command:
                print("\nreset 또는 quit을 입력하세요.")
        except queue.Empty:
            pass

        direction = "center" if abs(angle) < 0.5 else ("left" if angle > 0 else "right")
        if now >= next_csv:
            logger.write(mode=mode, gyro_z_dps=f"{rate:.3f}", angle_deg=f"{angle:.3f}", direction=direction)
            next_csv = now + CSV_INTERVAL_SECONDS
        if now >= next_print:
            print(f"\r{describe_angle(angle):<30} Z={rate:+7.2f} °/s", end="", flush=True)
            next_print = now + PRINT_INTERVAL_SECONDS
        time.sleep(0.005)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--invert",
        action="store_true",
        help="센서 장착 방향 때문에 좌우 표시가 반대로 나올 때 사용",
    )
    parser.add_argument("--simulate", action="store_true", help="MPU6050 없이 모의 회전값 생성")
    parser.add_argument("--csv", nargs="?", const=AUTO_CSV, help="CSV 저장 경로(생략 시 logs에 자동 생성)")
    args = parser.parse_args()
    direction_sign = -1.0 if args.invert else 1.0
    fields = ["timestamp", "mode", "gyro_z_dps", "angle_deg", "direction"]

    try:
        with CsvLogger(csv_path(args.csv, "imu"), fields) as logger:
            if args.simulate:
                print("모의 패턴: 정지 → 왼쪽 약 30도 → 정지 → 오른쪽 약 45도")
                return run_measurement(simulated_rate, direction_sign, logger, "simulate")

            from smbus2 import SMBus

            with SMBus(I2C_BUS) as bus:
                address = find_mpu6050(bus)
                bus.write_byte_data(address, PWR_MGMT_1, 0x00)
                bus.write_byte_data(address, GYRO_CONFIG, 0x00)
                time.sleep(0.1)
                bias_dps = calibrate_gyro(bus, address)

                def hardware_rate(_: float) -> float:
                    raw = read_word_signed(bus, address, GYRO_ZOUT_H) / GYRO_SCALE_250_DPS
                    return raw - bias_dps

                return run_measurement(hardware_rate, direction_sign, logger, "hardware")
    except (OSError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
