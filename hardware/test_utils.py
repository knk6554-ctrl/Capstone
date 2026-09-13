"""Shared CSV helpers for Raspberry Pi hardware test scripts."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

AUTO_CSV = "AUTO"


def csv_path(value: str | None, prefix: str) -> Path | None:
    if value is None:
        return None
    if value == AUTO_CSV:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(__file__).resolve().parent / "logs" / f"{prefix}_{stamp}.csv"
    else:
        path = Path(value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class CsvLogger:
    def __init__(self, path: Path | None, fieldnames: list[str]) -> None:
        self.path = path
        self._file = None
        self._writer = None
        if path is not None:
            self._file = path.open("w", newline="", encoding="utf-8-sig")
            self._writer = csv.DictWriter(self._file, fieldnames=fieldnames)
            self._writer.writeheader()
            self._file.flush()
            print(f"CSV 기록: {path}")

    def write(self, **values: Any) -> None:
        if self._writer is None or self._file is None:
            return
        self._writer.writerow({"timestamp": datetime.now().isoformat(timespec="milliseconds"), **values})
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()

    def __enter__(self) -> CsvLogger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
