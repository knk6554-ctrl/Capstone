import argparse
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "hardware" / "real"
if str(REAL_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_DIR))

spec = importlib.util.spec_from_file_location("wayband_hardware_main", REAL_DIR / "main.py")
hardware_main = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hardware_main)


class FakeMapApi:
    instances = []

    def __init__(self, _server_url, **_kwargs):
        self.poll_count = 0
        self.__class__.instances.append(self)

    def poll(self):
        self.poll_count += 1
        return []


class HardwareMainTests(unittest.IsolatedAsyncioTestCase):
    async def cancel_after_start(self, coroutine):
        task = asyncio.create_task(coroutine)
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_map_only_cleanup_does_not_reference_dashboard_locals(self):
        args = argparse.Namespace(server_url="http://unused", simulate_ble=True)
        with patch.object(hardware_main, "MapApi", FakeMapApi):
            await self.cancel_after_start(hardware_main.run_map_only(args))

    async def test_obstacle_only_never_polls_map_server(self):
        FakeMapApi.instances.clear()
        args = argparse.Namespace(
            map_only=False,
            server_url="http://unused",
            baseline_down_mm=700,
            invert_imu=False,
            skip_front=False,
            simulate_sensors=True,
            simulate_ble=True,
            simulate_imu=True,
            terminal=False,
            obstacle_only=True,
        )
        with patch.object(hardware_main, "MapApi", FakeMapApi):
            await self.cancel_after_start(hardware_main.run(args))
        self.assertEqual(FakeMapApi.instances[0].poll_count, 0)


if __name__ == "__main__":
    unittest.main()
