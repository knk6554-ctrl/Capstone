from __future__ import annotations

import time


class TofRig:
    def __init__(self, cfg):
        self.cfg = cfg
        self.bus = None
        self.l5 = {}
        self.l1 = {}

    def select(self, channel: int) -> None:
        self.bus.write_byte(self.cfg.tca_address, 1 << channel)
        time.sleep(0.002)

    def start(self) -> None:
        from smbus2 import SMBus
        import qwiic_vl53l1x
        import qwiic_vl53l5cx

        self.bus = SMBus(self.cfg.i2c_bus)
        for channel in (self.cfg.front_channel, self.cfg.down_channel):
            self.select(channel)
            sensor = qwiic_vl53l5cx.QwiicVL53L5CX(address=0x29)
            if not sensor.is_connected() or not sensor.begin():
                raise RuntimeError(f"VL53L5CX CH{channel} 초기화 실패")
            sensor.set_resolution(64)
            sensor.start_ranging()
            self.l5[channel] = sensor
        for channel in (self.cfg.left_channel, self.cfg.right_channel):
            self.select(channel)
            sensor = qwiic_vl53l1x.QwiicVL53L1X(address=0x29)
            if sensor.sensor_init() not in (None, 0):
                raise RuntimeError(f"VL53L1X CH{channel} 초기화 실패")
            self.l1[channel] = sensor

    def _frame(self, channel: int):
        self.select(channel)
        sensor = self.l5[channel]
        if not sensor.check_data_ready():
            return None
        return [value if 0 < value <= 4000 else None for value in sensor.get_ranging_data().distance_mm]

    def _distance(self, channel: int):
        self.select(channel)
        sensor = self.l1[channel]
        sensor.start_ranging()
        time.sleep(0.01)
        value = sensor.get_distance()
        sensor.stop_ranging()
        return value if 0 < value <= 4000 else None

    def snapshot(self):
        front = self._frame(self.cfg.front_channel)
        down = self._frame(self.cfg.down_channel)
        if front is None or down is None:
            return None
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
