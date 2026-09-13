"""Prototype stair detector using front/down VL53L5CX sensors via TCA9548A."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass

from test_utils import AUTO_CSV, CsvLogger, csv_path

I2C_BUS = 1
TCA9548A_ADDRESS = 0x70
SENSOR_ADDRESS = 0x29
FRONT_CHANNEL = 0
DOWN_CHANNEL = 1
RESOLUTION = 8 * 8
CALIBRATION_FRAMES = 20
REQUIRED_CONSECUTIVE_FRAMES = 3
DROP_DELTA_MM = 180
FRONT_NEAR_MAX_MM = 1200
RISER_DEPTH_DELTA_MM = 180


@dataclass(frozen=True)
class StairReading:
    state: str
    front_lower_mm: int | None
    front_upper_mm: int | None
    down_mm: int | None


def select_channel(bus: object, channel: int) -> None:
    bus.write_byte(TCA9548A_ADDRESS, 1 << channel)
    time.sleep(0.002)


def valid(values: list[int]) -> list[int]:
    return [value for value in values if 0 < value <= 4000]


def median_or_none(values: list[int]) -> int | None:
    usable = valid(values)
    return round(statistics.median(usable)) if usable else None


def classify_stairs(values_front: list[int], values_down: list[int], baseline_down: int) -> StairReading:
    # VL53L5CX 배열의 앞 4행/뒤 4행을 상·하 영역으로 사용한다.
    # 센서가 거꾸로 장착됐다면 두 슬라이스를 서로 바꿔야 한다.
    front_upper = median_or_none(values_front[:32])
    front_lower = median_or_none(values_front[32:])
    down = median_or_none(values_down)

    if down is None:
        state = "하향 센서값 없음"
    elif down >= baseline_down + DROP_DELTA_MM:
        state = "내려가는 계단 감지"
    elif (
        front_lower is not None
        and front_upper is not None
        and front_lower <= FRONT_NEAR_MAX_MM
        and front_upper - front_lower >= RISER_DEPTH_DELTA_MM
    ):
        state = "올라가는 계단 감지"
    else:
        state = "평지"
    return StairReading(state, front_lower, front_upper, down)


def initialize_sensor(bus: object, channel: int, label: str) -> object:
    import qwiic_vl53l5cx

    select_channel(bus, channel)
    sensor = qwiic_vl53l5cx.QwiicVL53L5CX(address=SENSOR_ADDRESS)
    if not sensor.is_connected() or not sensor.begin():
        raise RuntimeError(f"{label} VL53L5CX 초기화 실패 (TCA 채널 {channel})")
    sensor.set_resolution(RESOLUTION)
    sensor.start_ranging()
    return sensor


def read_frame(bus: object, sensor: object, channel: int) -> list[int] | None:
    select_channel(bus, channel)
    if not sensor.check_data_ready():
        return None
    return list(sensor.get_ranging_data().distance_mm)


def collect_down_baseline(bus: object, sensor: object) -> int:
    samples: list[int] = []
    print("하향 거리 보정 중입니다. 평지에 놓고 움직이지 마세요...")
    while len(samples) < CALIBRATION_FRAMES:
        frame = read_frame(bus, sensor, DOWN_CHANNEL)
        if frame is not None:
            value = median_or_none(frame)
            if value is not None:
                samples.append(value)
        time.sleep(0.02)
    baseline = round(statistics.median(samples))
    print(f"평지 기준 하향 거리: {baseline} mm")
    return baseline


def simulated_frames(elapsed: float) -> tuple[list[int], list[int]]:
    phase = elapsed % 12.0
    if 3.0 <= phase < 6.0:
        return [1150] * 32 + [700] * 32, [500] * 64  # 올라가는 계단
    if 9.0 <= phase < 12.0:
        return [1300] * 64, [780] * 64  # 내려가는 계단
    return [1400] * 64, [500] * 64  # 평지


def run_detection(frame_source: object, baseline: int, logger: CsvLogger, mode: str) -> None:
    print("계단 감지 시작 (Ctrl+C로 종료)")
    pending_state = "평지"
    pending_count = 0
    displayed_state = ""
    started = time.monotonic()
    while True:
        frames = frame_source(time.monotonic() - started)
        if frames is None:
            time.sleep(0.01)
            continue
        front, down = frames
        reading = classify_stairs(front, down, baseline)
        if reading.state == pending_state:
            pending_count += 1
        else:
            pending_state = reading.state
            pending_count = 1
        if pending_count >= REQUIRED_CONSECUTIVE_FRAMES:
            displayed_state = pending_state

        logger.write(
            mode=mode,
            baseline_down_mm=baseline,
            down_mm=reading.down_mm,
            front_upper_mm=reading.front_upper_mm,
            front_lower_mm=reading.front_lower_mm,
            candidate_state=reading.state,
            displayed_state=displayed_state or "checking",
        )
        print(
            f"\r{displayed_state or '확인 중'} | 하향={reading.down_mm} mm "
            f"전방상={reading.front_upper_mm} mm 전방하={reading.front_lower_mm} mm    ",
            end="",
            flush=True,
        )
        time.sleep(0.05 if mode == "simulate" else 0.03)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="센서 없이 평지/계단 모의값 생성")
    parser.add_argument("--csv", nargs="?", const=AUTO_CSV, help="CSV 저장 경로(생략 시 logs에 자동 생성)")
    args = parser.parse_args()
    fields = [
        "timestamp", "mode", "baseline_down_mm", "down_mm", "front_upper_mm",
        "front_lower_mm", "candidate_state", "displayed_state",
    ]
    try:
        with CsvLogger(csv_path(args.csv, "stairs"), fields) as logger:
            if args.simulate:
                print("모의 패턴: 평지 → 올라가는 계단 → 평지 → 내려가는 계단")
                run_detection(lambda elapsed: simulated_frames(elapsed), 500, logger, "simulate")
            else:
                from smbus2 import SMBus

                with SMBus(I2C_BUS) as bus:
                    front_sensor = initialize_sensor(bus, FRONT_CHANNEL, "전방")
                    down_sensor = initialize_sensor(bus, DOWN_CHANNEL, "하향")
                    baseline = collect_down_baseline(bus, down_sensor)

                    def hardware_frames(_: float) -> tuple[list[int], list[int]] | None:
                        front = read_frame(bus, front_sensor, FRONT_CHANNEL)
                        down = read_frame(bus, down_sensor, DOWN_CHANNEL)
                        return None if front is None or down is None else (front, down)

                    run_detection(hardware_frames, baseline, logger, "hardware")
    except KeyboardInterrupt:
        print("\n감지를 종료합니다.")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
