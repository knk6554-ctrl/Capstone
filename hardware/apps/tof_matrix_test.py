from __future__ import annotations

import argparse
import math
import time

from test_utils import AUTO_CSV, CsvLogger, csv_path
from wayband_hw.core.detection import median_mm, roi, valid


def print_grid(label: str, frame: list[int | None], frame_no: int, fps: float) -> None:
    usable = [value for value in frame if valid(value)]
    center = roi(frame, range(2, 7), range(2, 6))
    print(f"\n[{label}] frame={frame_no} fps={fps:.1f} min={min(usable) if usable else '---'} mm ROI median={median_mm(center) or '---'} mm")
    for row in range(8):
        print(" ".join(" ---" if not valid(value) else f"{value:4d}" for value in frame[row * 8:(row + 1) * 8]))


def simulated_frame(base: int, elapsed: float, obstacle: bool = False) -> list[int | None]:
    values = [round(base + 25 * math.sin(elapsed + index * 0.2)) for index in range(64)]
    if obstacle:
        values[27:29] = [450, 470]
    return values


def run_simulation(logger: CsvLogger) -> None:
    started = previous = time.monotonic()
    frame_no = 0
    while True:
        now = time.monotonic(); elapsed = now - started; frame_no += 1
        fps = 1 / max(now - previous, 0.001); previous = now
        front = simulated_frame(1500, elapsed, int(elapsed) % 8 >= 4)
        down = simulated_frame(700 if int(elapsed) % 12 < 8 else 1050, elapsed)
        left = round(900 + 300 * math.sin(elapsed)); right = round(1300 + 250 * math.sin(elapsed + 1))
        print_grid("전방", front, frame_no, fps); print_grid("하방", down, frame_no, fps)
        print(f"좌측={left} mm / 우측={right} mm")
        logger.write(mode="simulate", sensor="front", frame=frame_no, fps=f"{fps:.2f}", side_mm="", minimum_mm=min(front), roi_median_mm=median_mm(roi(front, range(2, 7), range(2, 6))), cells=";".join(map(str, front)))
        logger.write(mode="simulate", sensor="down", frame=frame_no, fps=f"{fps:.2f}", side_mm="", minimum_mm=min(down), roi_median_mm=median_mm(roi(down, range(4, 8), range(1, 7))), cells=";".join(map(str, down)))
        logger.write(mode="simulate", sensor="sides", frame=frame_no, fps=f"{fps:.2f}", side_mm=f"{left};{right}", minimum_mm="", roi_median_mm="", cells="")
        time.sleep(0.25)


def run_hardware(logger: CsvLogger) -> None:
    # Reuse the proven sensor initialisation functions while presenting richer output.
    from smbus2 import SMBus
    from tof_distance import L1X_CHANNELS, L5CX_CHANNELS, initialize_l1x, initialize_l5cx, select_channel

    with SMBus(1) as bus:
        l5 = initialize_l5cx(bus); l1 = initialize_l1x(bus)
        frame_no = {channel: 0 for channel in L5CX_CHANNELS}; previous = {channel: time.monotonic() for channel in L5CX_CHANNELS}
        while True:
            for channel, label in L5CX_CHANNELS.items():
                select_channel(bus, channel); sensor = l5[channel]
                if not sensor.check_data_ready(): continue
                raw = list(sensor.get_ranging_data().distance_mm)
                frame = [value if valid(value) else None for value in raw]
                now = time.monotonic(); fps = 1 / max(now - previous[channel], .001); previous[channel] = now; frame_no[channel] += 1
                print_grid(label, frame, frame_no[channel], fps)
                selection = roi(frame, range(2, 7), range(2, 6)) if channel == 0 else roi(frame, range(4, 8), range(1, 7))
                usable = [v for v in frame if valid(v)]
                logger.write(mode="hardware", sensor="front" if channel == 0 else "down", frame=frame_no[channel], fps=f"{fps:.2f}", side_mm="", minimum_mm=min(usable) if usable else "", roi_median_mm=median_mm(selection), cells=";".join("" if v is None else str(v) for v in frame))
            sides = []
            for channel, label in L1X_CHANNELS.items():
                select_channel(bus, channel); sensor = l1[channel]; sensor.start_ranging(); time.sleep(.01); value = sensor.get_distance(); sensor.stop_ranging()
                sides.append(value if valid(value) else None); print(f"{label}: {value if valid(value) else '---'} mm")
            logger.write(mode="hardware", sensor="sides", frame=max(frame_no.values()), fps="", side_mm=";".join("" if v is None else str(v) for v in sides), minimum_mm="", roi_median_mm="", cells="")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--simulate", action="store_true"); parser.add_argument("--csv", nargs="?", const=AUTO_CSV)
    args = parser.parse_args(); fields = ["timestamp", "mode", "sensor", "frame", "fps", "side_mm", "minimum_mm", "roi_median_mm", "cells"]
    try:
        with CsvLogger(csv_path(args.csv, "tof_matrix"), fields) as logger:
            run_simulation(logger) if args.simulate else run_hardware(logger)
    except KeyboardInterrupt: print("\n측정 종료")

