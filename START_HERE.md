# WayBand 시작 안내

이 배포본은 다음 세 부분으로 나뉩니다.

```text
WayBand/
├─ app.py                 카카오맵 FastAPI 서버 시작 파일
├─ web/                   카카오맵 웹 화면
├─ wayband/               경로 검색·회전각·진동 명령 서버 코드
└─ hardware/
   ├─ test/               부품별 테스트 실행기
   ├─ real/               Raspberry Pi 실전 통합 코드
   ├─ wayband_hw/         공통 IMU·BLE·판정 코드
   └─ firmware/           ESP32 팔찌 펌웨어
```

## 1. 지도 웹 서버 실행

Windows PowerShell에서 프로젝트 루트로 이동합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에서 다음 두 값을 본인의 카카오 개발자 키로 설정합니다.

```dotenv
KAKAO_REST_API_KEY=본인의_REST_API_KEY
KAKAO_JAVASCRIPT_KEY=본인의_JAVASCRIPT_KEY
```

카카오 개발자 콘솔의 JavaScript 키 허용 도메인에 아래 주소를 등록합니다.

```text
http://localhost:8000
http://127.0.0.1:8000
```

서버를 실행합니다.

```powershell
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

PC에서는 `http://localhost:8000/`을 엽니다. Raspberry Pi가 다른 장치라면
`http://PC의_IP주소:8000/`을 사용합니다. Windows 방화벽에서 사설 네트워크의
8000번 포트 허용이 필요할 수 있습니다.

## 2. 테스트 코드 실행

Raspberry Pi에서 `hardware` 의존성을 먼저 설치합니다.

```bash
cd hardware
python3 -m venv .venv
.venv/bin/pip install -r requirements-rpi.txt
```

각 부품을 따로 시험합니다.

```bash
cd test
../.venv/bin/python main.py wrist
../.venv/bin/python main.py rotation --timeout 10
../.venv/bin/python main.py tof
../.venv/bin/python main.py stairs
```

- `wrist`: `L` 또는 `R`을 입력하면 해당 팔찌가 3초 진동합니다.
- `rotation`: `-90~+90`을 입력합니다. 음수는 왼쪽, 양수는 오른쪽입니다.
  목표각에 도달하면 즉시 정지하며 10초가 지나도 도달하지 못하면 강제 정지합니다.
- `tof`: 전방·하방 8×8 거리표와 좌·우 거리를 표시합니다.
- `stairs`: 전방·하방 데이터를 이용한 상행·하행 계단 후보를 표시합니다.

## 3. PC에서 실전 코드 모의 실행

지도 서버를 켠 상태에서 별도 터미널을 열어 실행합니다.

```powershell
cd hardware\real
python main.py --simulate-sensors --simulate-ble --simulate-imu `
  --server-url http://127.0.0.1:8000
```

모의 센서가 왼쪽 전방 장애물을 만들면 오른쪽 회피각을 계산하고, 장애물을 지난 뒤
반대 각도만큼 돌아오는 메시지가 출력됩니다.

## 4. Raspberry Pi 실전 실행

지도 서버 PC와 Raspberry Pi가 같은 네트워크에 있어야 합니다.

```bash
cd hardware/real
../.venv/bin/python main.py \
  --server-url http://PC의_IP주소:8000 \
  --baseline-down-mm 700
```

MPU6050에서 좌우 부호가 반대로 나오면 `--invert-imu`를 추가합니다.

```bash
../.venv/bin/python main.py \
  --server-url http://PC의_IP주소:8000 \
  --baseline-down-mm 700 \
  --invert-imu
```

`baseline-down-mm`는 장치를 착용하고 평지에 섰을 때 하방 센서에서 측정한 실제
거리로 변경해야 합니다.

## 5. 실제 길안내 순서

```text
웹에서 출발지·목적지 선택
→ 카카오 도보 경로 생성
→ 웹에서 길안내 시작
→ 휴대폰 GPS 위치를 서버에 전달
→ 다음 경로 구간의 실제 회전각 계산
→ Raspberry Pi가 목표각 명령 수신
→ 왼쪽 또는 오른쪽 팔찌 연속 진동
→ MPU6050이 목표각 도달 확인
→ 즉시 진동 정지
```

목표각에 10초 안에 도달하지 못하면 진동을 멈추고 실패 신호를 보냅니다.

## 6. 장애물 회피 순서

```text
전방 8×8에서 장애물 확인
→ 전방 장애물 진동
→ 8×8 빈 공간과 좌우 센서 비교
→ -30°~+30°에서 안전한 회피각 결정
→ 해당 팔찌가 목표각까지 진동
→ 장애물 옆을 통과
→ 반대 각도만큼 회전
→ 기존 방향과 평행하게 직진
```

좌우 모두 안전거리가 부족하면 임의로 이동 방향을 정하지 않고 정지 경고를 냅니다.

## 7. 안전 주의

이 코드는 시제품 시험용입니다. 계단, 낙차, 횡단보도 및 장애물 판정은 흰지팡이,
보행 신호 확인 또는 보조자를 대체하지 않습니다. 실제 보행 전에 실내 정지 시험,
넓은 공간 시험, 보조자 동행 시험 순으로 검증해야 합니다.
