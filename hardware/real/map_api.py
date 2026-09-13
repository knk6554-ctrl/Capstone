from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen

from control import CommandKind, NavigationCommand


class MapApi:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        self.sequence = 0

    def poll(self) -> list[NavigationCommand]:
        query = urlencode({"after_sequence": self.sequence, "limit": 20})
        with urlopen(f"{self.server_url}/api/haptics?{query}", timeout=2) as response:
            commands = json.loads(response.read().decode("utf-8"))["commands"]

        result: list[NavigationCommand] = []
        for command in commands:
            self.sequence = max(self.sequence, int(command["sequence"]))
            if command.get("source") != "NAVIGATION":
                continue
            pattern = command.get("pattern")
            if pattern in {"TURN_NOW", "UTURN_NOW"}:
                angle = command.get("targetAngleDegrees")
                if angle is None:
                    target = command.get("target")
                    angle = -90.0 if target == "LEFT_WRIST" else 90.0
                result.append(NavigationCommand(CommandKind.TURN, float(angle), command.get("message", "")))
            elif pattern == "CROSSWALK":
                result.append(NavigationCommand(CommandKind.CROSSWALK, message=command.get("message", "")))
            elif pattern == "ARRIVED":
                result.append(NavigationCommand(CommandKind.ARRIVED, message=command.get("message", "")))
        return result
