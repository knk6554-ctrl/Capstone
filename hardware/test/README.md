# WayBand test

하드웨어를 하나씩 확인하는 테스트용 프로그램은 이 폴더의 `main.py`에서 선택해
실행합니다. 실제 통합 제어기는 `../real`에 있습니다.

```bash
cd hardware/test
python3 main.py wrist
python3 main.py rotation --timeout 10
python3 main.py tof
python3 main.py stairs
```

- `wrist`: L/R 입력 시 선택 팔찌 3초 진동
- `rotation`: 음수=왼쪽, 양수=오른쪽 목표각까지 진동, 기본 10초 타임아웃
- `tof`: 전방·하방 8×8과 좌·우 단일 거리 출력
- `stairs`: 전방·하방 8×8 계단 후보 시험
