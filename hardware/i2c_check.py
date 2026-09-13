"""Raspberry Pi I2C/TCA9548A/VL53L5CX connection check."""

from __future__ import annotations

import sys
from smbus2 import SMBus

I2C_BUS = 1
TCA9548A_ADDRESS = 0x70
VL53L5CX_ADDRESS = 0x29
MPU6050_ADDRESSES = {0x68, 0x69}
EXPECTED_TOF_CHANNELS = {0, 1, 2, 3}


def select_channel(bus: SMBus, channel: int | None) -> None:
    """Select one TCA9548A channel, or disable every channel with None."""
    value = 0 if channel is None else 1 << channel
    bus.write_byte(TCA9548A_ADDRESS, value)


def scan(bus: SMBus) -> list[int]:
    found: list[int] = []
    for address in range(0x03, 0x78):
        try:
            bus.read_byte(address)
        except OSError:
            continue
        found.append(address)
    return found


def main() -> int:
    print(f"I2C bus {I2C_BUS} 검사")
    try:
        with SMBus(I2C_BUS) as bus:
            main_devices = scan(bus)
            print("메인 버스:", " ".join(f"0x{x:02X}" for x in main_devices) or "없음")

            imu_addresses = sorted(MPU6050_ADDRESSES.intersection(main_devices))
            if imu_addresses:
                print(f"MPU6050 연결 확인: 0x{imu_addresses[0]:02X} (거리 측정에는 사용 안 함)")
            else:
                print("참고: MPU6050(0x68/0x69)은 보이지 않습니다. 거리 측정에는 영향 없습니다.")

            if TCA9548A_ADDRESS not in main_devices:
                print("실패: TCA9548A(0x70)가 보이지 않습니다.")
                print("배선, 전원, raspi-config의 I2C 활성화를 확인하세요.")
                return 1

            detected_channels: set[int] = set()
            for channel in range(8):
                select_channel(bus, channel)
                devices = [x for x in scan(bus) if x != TCA9548A_ADDRESS]
                labels = " ".join(f"0x{x:02X}" for x in devices) or "없음"
                is_tof = VL53L5CX_ADDRESS in devices
                if is_tof:
                    detected_channels.add(channel)
                expected_name = {
                    0: "VL53L5CX 전방",
                    1: "VL53L5CX 하향",
                    2: "VL53L1X 좌측",
                    3: "VL53L1X 우측",
                }.get(channel)
                suffix = f"  <- {expected_name}" if is_tof and expected_name else ""
                print(f"TCA 채널 {channel}: {labels}{suffix}")

            select_channel(bus, None)
            print(f"\n결과: ToF 연결 채널 {sorted(detected_channels)}")
            # Both VL53L5CX and VL53L1X use 0x29, so an address scan cannot
            # distinguish the models. The distance test performs that check.
            return 0 if detected_channels == EXPECTED_TOF_CHANNELS else 2
    except PermissionError:
        print("실패: /dev/i2c-1 권한이 없습니다. 사용자 계정을 i2c 그룹에 추가하세요.")
        return 1
    except FileNotFoundError:
        print("실패: /dev/i2c-1이 없습니다. sudo raspi-config에서 I2C를 활성화하세요.")
        return 1
    except OSError as exc:
        print(f"I2C 오류: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
