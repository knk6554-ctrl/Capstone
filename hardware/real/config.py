from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    server_url: str = "http://127.0.0.1:8000"
    i2c_bus: int = 1
    imu_address: int = 0x68
    imu_invert: bool = False
    tca_address: int = 0x70
    front_channel: int = 0
    down_channel: int = 1
    left_channel: int = 2
    right_channel: int = 3
    baseline_down_mm: int = 700
    front_warning_mm: int = 1000
    front_critical_mm: int = 500
    side_blocked_mm: int = 500
    side_clear_mm: int = 650
    down_drop_delta_mm: int = 180
    stair_rise_delta_mm: int = 180
    required_frames: int = 3
    avoidance_clear_frames: int = 5
    tof_horizontal_fov_degrees: float = 60.0
    minimum_corridor_width_mm: int = 600
    rotation_tolerance_degrees: float = 4.0
    rotation_timeout_seconds: float = 10.0
    loop_interval_seconds: float = 0.05
