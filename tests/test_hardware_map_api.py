import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "hardware" / "real"
if str(REAL_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_DIR))

import map_api  # noqa: E402
from control import CommandKind  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _command(sequence: int, **overrides) -> dict:
    base = {
        "sequence": sequence,
        "commandId": f"cmd-{sequence}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "target": "RIGHT_WRIST",
        "pattern": "TURN_NOW",
        "source": "NAVIGATION",
        "message": "우회전",
        "intensity": 0.9,
        "pulseCount": 3,
        "pulseOnMs": 220,
        "pulseOffMs": 180,
        "targetAngleDegrees": 42.0,
    }
    base.update(overrides)
    return base


class SequencePersistenceTests(unittest.TestCase):
    def test_fresh_state_path_starts_at_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = map_api.MapApi("http://unused", state_path=Path(tmp) / "state.json")
            self.assertEqual(api.sequence, 0)

    def test_sequence_is_persisted_and_reloaded_across_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            api = map_api.MapApi("http://unused", state_path=state_path)
            with patch.object(map_api, "urlopen", return_value=FakeResponse({"commands": [_command(5)]})):
                api.poll()
            self.assertEqual(api.sequence, 5)
            self.assertEqual(json.loads(state_path.read_text())["lastSequence"], 5)

            # 프로그램이 재시작된 상황을 흉내 — 같은 state_path로 새 인스턴스를 만든다.
            restarted = map_api.MapApi("http://unused", state_path=state_path)
            self.assertEqual(restarted.sequence, 5)

    def test_corrupt_state_file_falls_back_to_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("not json")
            api = map_api.MapApi("http://unused", state_path=state_path)
            self.assertEqual(api.sequence, 0)


class PollFilteringTests(unittest.TestCase):
    def _api(self, tmp, **kwargs):
        return map_api.MapApi("http://unused", state_path=Path(tmp) / "state.json", **kwargs)

    def test_stale_command_is_dropped_but_sequence_still_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp, max_age_seconds=5.0)
            old_created_at = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            payload = {"commands": [_command(1, pattern="CROSSWALK", createdAt=old_created_at)]}
            with patch.object(map_api, "urlopen", return_value=FakeResponse(payload)):
                result = api.poll()

            self.assertEqual(result, [])
            self.assertEqual(api.sequence, 1)

    def test_fresh_command_within_max_age_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp, max_age_seconds=5.0)
            payload = {"commands": [_command(1, pattern="CROSSWALK")]}
            with patch.object(map_api, "urlopen", return_value=FakeResponse(payload)):
                result = api.poll()

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].kind, CommandKind.CROSSWALK)

    def test_non_navigation_source_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp)
            payload = {"commands": [_command(1, source="TOF", pattern="ARRIVED")]}
            with patch.object(map_api, "urlopen", return_value=FakeResponse(payload)):
                result = api.poll()

            self.assertEqual(result, [])
            self.assertEqual(api.sequence, 1)

    def test_turn_now_uses_server_angle_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp)
            payload = {"commands": [_command(1, targetAngleDegrees=-63.5)]}
            with patch.object(map_api, "urlopen", return_value=FakeResponse(payload)):
                result = api.poll()

            self.assertEqual(result[0].kind, CommandKind.TURN)
            self.assertEqual(result[0].angle_degrees, -63.5)

    def test_turn_now_falls_back_to_90_degrees_when_angle_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp)
            payload = {
                "commands": [_command(1, target="LEFT_WRIST", targetAngleDegrees=None)]
            }
            with patch.object(map_api, "urlopen", return_value=FakeResponse(payload)):
                result = api.poll()

            self.assertEqual(result[0].angle_degrees, -90.0)


if __name__ == "__main__":
    unittest.main()
