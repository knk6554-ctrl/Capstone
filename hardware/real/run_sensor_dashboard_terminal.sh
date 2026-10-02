#!/bin/bash
# 터미널에서 회전각 등을 바로 확인하기 위한 래퍼 — 대시 플래그를 직접 타이핑하다
# 글자가 깨지는 문제를 피하려고 고정된 옵션으로 실행한다.
cd "$(dirname "$0")" || exit 1
# requirements-rpi.txt는 보통 hardware/.venv에 설치된다 — 있으면 그 파이썬을
# 쓰고, 없으면(venv 없이 시스템 파이썬에 바로 설치한 경우) python3로 넘어간다.
if [ -x "../.venv/bin/python3" ]; then
    PYTHON="../.venv/bin/python3"
else
    PYTHON="python3"
fi
exec "$PYTHON" sensor_dashboard.py --terminal --server-url https://capstone-2jv4.onrender.com "$@"
