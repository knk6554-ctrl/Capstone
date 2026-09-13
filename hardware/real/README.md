# WayBand real

카카오 도보 경로, MPU6050 목표각 회전, 전방·하방 8×8 ToF, 좌·우 ToF와
양쪽 BLE 팔찌를 합친 실전용 Raspberry Pi 코드입니다.

## 동작

- 카카오 `TURN_NOW` 명령의 `targetAngleDegrees`만큼 해당 팔찌가 계속 진동합니다.
- 목표각 `±4°` 도달 또는 목표각 통과 시 즉시 멈춥니다.
- 10초 안에 목표각에 도달하지 못하면 강제 정지하고 양쪽에 실패 신호를 보냅니다.
- 횡단보도 15m 전 양쪽 `0.5초 → 0.3초 정지 → 0.5초`로 알립니다.
- 전방 장애물은 8×8 빈 통로의 중심과 실제 폭, 좌우 측면 거리를 함께 사용해
  `-30°~+30°` 회피각을 계산합니다.
- 장애물을 지나면 반대 각도만큼 회전해 기존 진행 방향과 평행하게 복귀합니다.
- 낙차·계단·충돌 위험은 지도 안내보다 우선합니다.

횡단보도 진동은 보행 신호가 아니라 횡단보도 접근 알림입니다. 사용자가 정지한 뒤
실제 보행 신호와 차량을 별도로 확인해야 합니다.

## 실행

```bash
cd hardware/real
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# PC 모의 시험
.venv/bin/python main.py --simulate-sensors --simulate-ble --simulate-imu

# Raspberry Pi 실제 실행
.venv/bin/python main.py --server-url http://서버IP:8000 --baseline-down-mm 700
```

MPU6050 방향이 반대로 표시되면 `--invert-imu`를 추가합니다. 실제 보행 전에 반드시
넓은 실내에서 센서별 정지 시험과 보조자 동행 시험을 먼저 수행하세요.
