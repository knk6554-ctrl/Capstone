# 벨트 게이트웨이 (라즈베리파이)

`/api/haptics`를 폴링해서 서버가 만든 진동 명령을 실제 모터로 재생하는 라즈베리파이용 코드입니다. `docs/HARDWARE_PROTOCOL.md`의 "진동 명령 가져오기" 규격을 그대로 구현합니다.

## 진동 의미(현재 서버 값 기준)

| 상황 | 대상 | 세기 | 재생 방식 |
|---|---|---|---|
| 좌/우회전 준비 (25m) | 해당 손목 | 0.55 | 고정 1회 × 220ms |
| 좌/우회전 시점 (8m) | 해당 손목 | 0.90 | **목표 각도만큼 실제로 돌 때까지 220/180ms 리듬으로 반복(최대 8초)** |
| 도착 | 양쪽 손목 | 0.75 | 고정 2회 × 700/250ms |
| 횡단보도 근접 | 양쪽 손목 | 0.80 | 고정 2회 × 300/220ms |
| 계단 근접 | 양쪽 손목 | 0.85 | 고정 3회 × 250/150ms |
| 경로 이탈 (3회 연속) | 양쪽 손목 | 1.00 | 고정 5회 × 120/100ms |
| ToF 경고 (600~1200mm) | 감지 방향 벨트 | 0.70 | 고정 2회 × 300/220ms |
| ToF 위험 (≤600mm) | 감지 방향 벨트 | 1.00 | 고정 5회 × 180/100ms |

유턴은 전용 패턴이 없습니다 — 경로 안내 문구·목록에는 계속 "유턴"으로 남지만 진동은 울리지 않습니다.

세기/횟수/ms 숫자는 `wayband/navigation.py`·`wayband/hazard.py`가 만들어서 `/api/haptics` 응답의 `pulseCount`/`pulseOnMs`/`pulseOffMs`/`intensity` 필드로 그대로 보냅니다. **`belt/pattern_player.py`는 이 숫자를 다시 정의하지 않고 서버가 보낸 값을 그대로 재생만 합니다** — 서버 쪽 값을 바꿔도 이 코드는 다시 배포할 필요가 없습니다.

### `TURN_NOW`는 왜 다른가 — IMU 각도 추적

GPS 거리만으로는 "안내는 했지만 사용자가 실제로 돌았는지" 알 수 없습니다. 그래서 회전 시점(`TURN_NOW`)만은 고정 횟수로 끝내지 않고:

1. 서버가 카카오 경로 좌표로 계산한 목표 회전각(`targetAngleDegrees`, 부호 있는 도 단위 — 양수=우회전/음수=좌회전)을 명령에 실어 보냅니다.
2. 벨트는 해당 손목을 220/180ms 리듬으로 계속 진동시키면서, 자체 IMU의 Z축 각속도를 적분해 실제 회전량을 추적합니다.
3. 누적 회전량이 목표 각도의 ±8도 안에 들어오면(`turn_tracker.ANGLE_TOLERANCE_DEGREES`) 즉시 진동을 멈춥니다.
4. **8초(`turn_tracker.TIMEOUT_SECONDS`) 안에 도달하지 못하면 — 센서 오차든 실제로 안 돌았든 원인과 무관하게 — 그냥 진동을 멈추고 포기합니다.** 다음 안내(다음 회전·횡단보도 등)는 GPS 기준으로 이미 독립적으로 계속 진행되므로 여기서 재시도하거나 대체 패턴을 재생하지 않습니다. 무한히 진동을 붙잡고 있는 쪽이 더 위험하다는 판단입니다(모터 소음·배터리·사용자 혼란).

`PREPARE_TURN`(25m 준비 알림)은 아직 회전 지점에 도착하지 않았으므로 각도를 보지 않고 예전처럼 고정 1회만 재생합니다. IMU가 배선되지 않았거나 초기화에 실패하면 `TURN_NOW`도 자동으로 고정 3회 재생으로 폴백합니다(`haptic_client.build_imu`).

참고 구현: `turn_tracker.py`(순수 로직, GPIO/IMU 없이 유닛 테스트됨), `imu.py`(IMU 추상화), `pattern_player.py`의 `can_play_turn`/`play_turn_command`.

## 파일 구성

- `config.py` — 서버 주소, 폴링 주기, GPIO 핀 매핑, IMU 사용 여부
- `motors.py` — GPIO 모터 구동 계층(`GpioMotor`)과 배선 전 테스트용 가짜 모터(`NullMotor`)
- `imu.py` — IMU(자이로 Z축) 추상화(`RealImu`)와 테스트용 `ScriptedImu`
- `turn_tracker.py` — 회전 시점(`TURN_NOW`)에서 목표 각도까지 진동을 유지하는 순수 로직(8초 타임아웃 포함)
- `pattern_player.py` — 명령 하나를 펄스 시퀀스로 바꿔 재생하는 순수 로직(하드웨어 의존 없음, 유닛 테스트 대상)
- `haptic_client.py` — 폴링 루프, 순번(`lastSequence`) 저장, 재시작/재연결 처리

## 배선

기본 BCM 핀 매핑(`config.py`의 `DEFAULT_MOTOR_PINS`, 실제 배선에 맞춰 수정):

| 물리 위치 | BCM 핀 |
|---|---|
| LEFT_WRIST | 17 |
| RIGHT_WRIST | 27 |
| BELT_FRONT_LEFT | 22 |
| BELT_FRONT_RIGHT | 23 |
| BELT_LEFT_SIDE | 24 |
| BELT_RIGHT_SIDE | 25 |

각 핀은 저항을 거쳐 모터 드라이버 트랜지스터/MOSFET의 베이스(게이트)에 연결하고, 모터에는 플라이백 다이오드를 반드시 답니다. `BOTH_WRISTS` 명령은 별도 핀이 아니라 `LEFT_WRIST`+`RIGHT_WRIST` 두 핀을 동시에 울리는 것으로 처리합니다(`pattern_player.py`의 `TARGET_MOTORS`).

IMU(`imu.py`의 `RealImu`, 기본 MPU6050 가정)는 I2C(SDA/SCL, 라즈베리파이 기본 `bus=1`, 주소 `0x68`)로 연결합니다. 실제로 다른 IMU를 쓴다면 `imu.py`의 `RealImu` 내부(임포트, `read_gyro_z_dps`)만 바꾸면 나머지 코드는 그대로 동작합니다. **부호 규약(시계방향=우회전=양수)이 실제 장착 방향과 맞는지 배선 후 반드시 실측하세요** — 뒤집혀 있으면 좌/우회전 판정이 반대로 동작합니다.

## 실행

```bash
cd Capstone            # 레포 루트
pip install -r belt/requirements.txt
python3 -m belt.haptic_client
```

서버 주소가 기본값(`http://127.0.0.1:8000`)과 다르면:

```bash
WAYBAND_SERVER_URL=http://192.168.0.10:8000 python3 -m belt.haptic_client
```

`Ctrl+C`(SIGINT)나 SIGTERM을 받으면 모든 모터를 끄고 종료합니다.

## 알려진 한계

- **ToF 장애물 경고는 지금 네트워크 왕복(서버 → `/api/haptics` → 이 코드)을 거칩니다.** README.md의 "중요한 기술적 한계"에 적힌 대로, 실제 배포에서는 벨트가 ToF 값을 직접 읽어 로컬로 즉시 판정·진동해야 안전합니다(Wi-Fi·서버가 끊겨도 장애물 경고는 살아있어야 함). 이 코드는 시연용 경로입니다.
- 서버 상태가 메모리에만 있어 서버가 재시작되면 명령 순번이 1부터 다시 시작합니다. 이 코드가 저장해둔 `state.json`의 `lastSequence`가 새 순번보다 크면 새 명령이 계속 필터링되어 안 옵니다 — 서버를 재시작했다면 `belt/state.json`을 지우거나 `lastSequence`를 0으로 바꾸세요.
- 팔찌 쪽 실제 BLE 전송은 아직 없습니다. 이 코드는 "벨트(라즈베리파이)가 모터를 직접 GPIO로 구동한다"고 가정합니다. 팔찌를 별도 장치로 분리하려면 `pattern_player.py`의 재생 결과를 BLE로 중계하는 계층을 추가하세요.
