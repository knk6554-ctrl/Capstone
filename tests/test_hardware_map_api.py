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


class ServerRestartDetectionTests(unittest.TestCase):
    def _api(self, tmp, **kwargs):
        return map_api.MapApi("http://unused", state_path=Path(tmp) / "state.json", **kwargs)

    def test_first_ever_poll_adopts_server_instance_id_without_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp)
            self.assertIsNone(api.server_instance_id)
            payload = FakeResponse({"commands": [_command(3)], "serverInstanceId": "instance-a"})

            with patch.object(map_api, "urlopen", return_value=payload) as mock_urlopen:
                result = api.poll()

            self.assertEqual(api.server_instance_id, "instance-a")
            self.assertEqual(api.sequence, 3)
            self.assertEqual(len(result), 1)
            self.assertEqual(mock_urlopen.call_count, 1)

    def test_server_restart_resets_sequence_and_retries_within_same_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp)
            first = FakeResponse({"commands": [_command(5)], "serverInstanceId": "instance-a"})
            with patch.object(map_api, "urlopen", return_value=first):
                api.poll()
            self.assertEqual(api.sequence, 5)

            # 서버가 재시작됐다: 새 instanceId, 순번은 1부터 다시 시작한다. 우리가
            # 보낸 after_sequence=5는 새 서버 기준으로 존재하지 않는 미래 순번이라
            # 빈 응답이 오고, 순번을 0으로 리셋한 뒤에야 새 명령을 받는다.
            empty_after_restart = FakeResponse({"commands": [], "serverInstanceId": "instance-b"})
            fresh_after_reset = FakeResponse(
                {"commands": [_command(2, pattern="STAIRS")], "serverInstanceId": "instance-b"}
            )
            with patch.object(
                map_api, "urlopen", side_effect=[empty_after_restart, fresh_after_reset]
            ) as mock_urlopen:
                result = api.poll()

            self.assertEqual(api.server_instance_id, "instance-b")
            self.assertEqual(api.sequence, 2)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].kind, CommandKind.STAIRS)
            self.assertEqual(mock_urlopen.call_count, 2)
            retry_url = mock_urlopen.call_args_list[1].args[0]
            self.assertIn("after_sequence=0", retry_url)

    def test_same_server_instance_id_does_not_reset_or_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api(tmp)
            first = FakeResponse({"commands": [_command(5)], "serverInstanceId": "instance-a"})
            with patch.object(map_api, "urlopen", return_value=first):
                api.poll()

            same = FakeResponse({"commands": [_command(6)], "serverInstanceId": "instance-a"})
            with patch.object(map_api, "urlopen", return_value=same) as mock_urlopen:
                api.poll()

            self.assertEqual(api.sequence, 6)
            self.assertEqual(mock_urlopen.call_count, 1)


class SaveFailureResilienceTests(unittest.TestCase):
    def test_state_save_failure_does_not_block_command_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = map_api.MapApi("http://unused", state_path=Path(tmp) / "state.json")
            payload = FakeResponse(
                {"commands": [_command(1, pattern="ARRIVED")], "serverInstanceId": "instance-a"}
            )

            with patch.object(map_api, "urlopen", return_value=payload), patch.object(
                map_api.Path, "write_text", side_effect=OSError("읽기 전용 파일시스템")
            ):
                result = api.poll()

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].kind, CommandKind.ARRIVED)
            self.assertEqual(api.sequence, 1)


if __name__ == "__main__":
    unittest.main()
