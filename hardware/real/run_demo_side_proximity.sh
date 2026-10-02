#!/bin/bash
# 좌우 근접(기본 300mm) 독립 진동 시연 — 실제 센서/팔찌로 실행, Render로 자동 전송.
cd "$(dirname "$0")" || exit 1
if [ -x "../.venv/bin/python3" ]; then
    PYTHON="../.venv/bin/python3"
else
    PYTHON="python3"
fi
exec "$PYTHON" demo_side_proximity.py "$@"
