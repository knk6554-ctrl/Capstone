"""Environment configuration without a third-party settings dependency."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv(path: Path = DEFAULT_ENV_PATH) -> None:
    """Load simple KEY=VALUE pairs while preserving existing environment values."""

    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        os.environ.setdefault(
            normalized_key,
            value.strip().strip('"').strip("'"),
        )


def _positive_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name}은 숫자여야 합니다.") from exc
    if value <= 0:
        raise RuntimeError(f"{name}은 0보다 커야 합니다.")
    return value


def _positive_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name}은 정수여야 합니다.") from exc
    if value <= 0:
        raise RuntimeError(f"{name}은 0보다 커야 합니다.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    kakao_rest_api_key: str
    kakao_javascript_key: str
    prepare_distance_meters: float
    turn_now_distance_meters: float
    off_route_distance_meters: float
    tof_warning_mm: int
    tof_critical_mm: int
    tof_clear_mm: int

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()
        rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
        javascript_key = os.environ.get("KAKAO_JAVASCRIPT_KEY", "").strip()
        missing = [
            name
            for name, value in (
                ("KAKAO_REST_API_KEY", rest_key),
                ("KAKAO_JAVASCRIPT_KEY", javascript_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                ".env에 다음 값을 설정하세요: " + ", ".join(missing)
            )

        settings = cls(
            kakao_rest_api_key=rest_key,
            kakao_javascript_key=javascript_key,
            prepare_distance_meters=_positive_float(
                "WAYBAND_PREPARE_DISTANCE_METERS", 25
            ),
            turn_now_distance_meters=_positive_float(
                "WAYBAND_TURN_NOW_DISTANCE_METERS", 8
            ),
            off_route_distance_meters=_positive_float(
                "WAYBAND_OFF_ROUTE_DISTANCE_METERS", 35
            ),
            tof_warning_mm=_positive_int("WAYBAND_TOF_WARNING_MM", 1200),
            tof_critical_mm=_positive_int("WAYBAND_TOF_CRITICAL_MM", 600),
            tof_clear_mm=_positive_int("WAYBAND_TOF_CLEAR_MM", 1500),
        )
        if settings.turn_now_distance_meters >= settings.prepare_distance_meters:
            raise RuntimeError(
                "WAYBAND_TURN_NOW_DISTANCE_METERS는 PREPARE 거리보다 작아야 합니다."
            )
        if not (
            settings.tof_critical_mm
            < settings.tof_warning_mm
            < settings.tof_clear_mm
        ):
            raise RuntimeError(
                "ToF 기준은 CRITICAL < WARNING < CLEAR 순서여야 합니다."
            )
        return settings
