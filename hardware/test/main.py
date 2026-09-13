from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path


PROGRAMS = {
    "wrist": "wrist_haptic_test.py",
    "rotation": "apps/rotation_target_test.py",
    "tof": "apps/tof_matrix_test.py",
    "stairs": "stair_detection.py",
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WayBand 하드웨어 개별 시험 실행기")
    parser.add_argument("program", choices=PROGRAMS)
    args, remaining = parser.parse_known_args()
    hardware_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(hardware_root))
    sys.argv = [PROGRAMS[args.program], *remaining]
    runpy.run_path(str(hardware_root / PROGRAMS[args.program]), run_name="__main__")
