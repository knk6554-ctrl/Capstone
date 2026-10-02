#!/bin/bash
# 터미널에서 회전각 등을 바로 확인하기 위한 래퍼 — 대시 플래그를 직접 타이핑하다
# 글자가 깨지는 문제를 피하려고 고정된 옵션으로 실행한다.
cd "$(dirname "$0")" || exit 1
exec python3 sensor_dashboard.py --terminal --no-web-dashboard "$@"
