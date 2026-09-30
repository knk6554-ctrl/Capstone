from __future__ import annotations

import time


class TofRig:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enable_front = getattr(cfg, "enable_front", True)
        self.bus = None
        self.l5 = {}
        self.l1 = {}

    def select(self, channel: int | None) -> None:
        self.bus.write_byte(
            self.cfg.tca_address,
            0 if channel is None else 1 << channel,
        )
        time.sleep(0.1 if channel is None else 0.2)

    def start(self) -> None:
        from smbus2 import SMBus
        import qwiic_vl53l1x
        import qwiic_vl53l5cx

        self.bus = SMBus(self.cfg.i2c_bus)
        channels = (self.cfg.front_channel, self.cfg.down_channel)
        for channel in channels:
            sensor = None
            last_error = None
            for attempt in range(1, 4):
                try:
                    self.select(None)
                    self.select(channel)
                    candidate = qwiic_vl53l5cx.QwiicVL53L5CX(address=0x29)
                    if not candidate.is_connected():
                        last_error = "0x29 응답 없음"
                    elif candidate.begin():
                        candidate.set_resolution(64)
                        candidate.start_ranging()
                        sensor = candidate
                        break
                    else:
                        last_error = "begin() 실패"
                except OSError as exc:
                    last_error = f"{exc}"
                print(
                    f"VL53L5CX CH{channel} 초기화 재시도 "
                    f"{attempt}/3: {last_error}"
                )
                time.sleep(0.5)
            if sensor is None:
                print(
                    f"경고: VL53L5CX CH{channel}을 사용할 수 없어 건너뜁니다: "
                    f"{last_error}"
                )
                continue
            self.l5[channel] = sensor
        for channel in (self.cfg.left_channel, self.cfg.right_channel):
            sensor = None
            last_error = None
            for attempt in range(1, 4):
                try:
                    self.select(None)
                    self.select(channel)
                    candidate = qwiic_vl53l1x.QwiicVL53L1X(address=0x29)
                    result = candidate.sensor_init()
                    if result in (None, 0):
                        sensor = candidate
                        break
                    last_error = f"반환값={result!r}"
                except OSError as exc:
                    last_error = f"{exc}"
                print(
                    f"VL53L1X CH{channel} 초기화 재시도 "
                    f"{attempt}/3: {last_error}"
                )
                time.sleep(0.5)
            if sensor is None:
                print(
                    f"경고: VL53L1X CH{channel}을 사용할 수 없어 건너뜁니다: "
                    f"{last_error}"
                )
                continue
            self.l1[channel] = sensor

    def _frame(self, channel: int):
        if channel not in self.l5:
            return None
        sensor = self.l5[channel]
        try:
            self.select(channel)
            if not sensor.check_data_ready():
                return None
            return [value if 0 < value <= 4000 else None for value in sensor.get_ranging_data().distance_mm]
        except OSError:
            return None

    def _distance(self, channel: int):
        if channel not in self.l1:
            return None
        sensor = self.l1[channel]
        try:
            self.select(channel)
            sensor.start_ranging()
            time.sleep(0.01)
            value = sensor.get_distance()
            sensor.stop_ranging()
        except OSError:
            return None
        return value if 0 < value <= 4000 else None

    def snapshot(self):
        front = self._frame(self.cfg.front_channel) or [None] * 64
        down = self._frame(self.cfg.down_channel) or [None] * 64
        return front, down, self._distance(self.cfg.left_channel), self._distance(self.cfg.right_channel)

    def close(self) -> None:
        if self.bus is not None:
            self.bus.close()


class SimulatedRig:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tick = 0

    def start(self) -> None:
        pass

    def snapshot(self):
        self.tick += 1
        front = [1800] * 64
        down = [self.cfg.baseline_down_mm] * 64
        phase = self.tick % 240
        if 60 <= phase < 120:
            for row in range(2, 7):
                for col in range(0, 4):
                    front[row * 8 + col] = 650
        return front, down, 900, 1800

    def close(self) -> None:
        pass
