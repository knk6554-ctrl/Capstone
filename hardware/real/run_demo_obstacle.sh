#!/bin/bash
# 장애물 회피 시연 — 실제 센서/팔찌로 실행, Render로 자동 전송.
cd "$(dirname "$0")" || exit 1
if [ -x "../.venv/bin/python3" ]; then
    PYTHON="../.venv/bin/python3"
else
    PYTHON="python3"
fi
exec "$PYTHON" demo_obstacle.py "$@"
