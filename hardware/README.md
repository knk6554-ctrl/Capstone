# Raspberry Pi + 혼합 ToF 센서 점검

새 구조는 `test/`(센서·팔찌 개별 시험)와 `real/`(카카오 길안내, IMU 목표각,
8×8 동적 회피 통합)로 구분합니다. 새 실전 실행은 `real/README.md`를 따르세요.

구성: Raspberry Pi I2C-1 -> TCA9548A(0x70) -> CH0 전방 VL53L5CX,
CH1 하향 VL53L5CX, CH2 좌측 VL53L1X, CH3 우측 VL53L1X(모두 0x29).
MPU6050은 메인 I2C 버스에 연결되어 있어도 프로그램에서 사용하지 않으며,
길 안내 위치는 기존 웹의 휴대폰 GPS를 사용한다.

## 1. Raspberry Pi I2C 활성화

```bash
sudo raspi-config nonint do_i2c 0
sudo reboot
```

기본 배선(Raspberry Pi 40핀): 3.3V=1번 핀, SDA=GPIO2/3번 핀,
SCL=GPIO3/5번 핀, GND=6번 핀. 센서와 TCA9548A는 3.3V 논리로 연결한다.

## 2. 새 SD 카드에서 환경 설치

```bash
sudo apt update
sudo apt install -y python3-venv i2c-tools
cd ~/wayband/hardware
python3 -m venv .venv
.venv/bin/pip install -r requirements-rpi.txt
```

## 3. I2C부터 확인

```bash
sudo i2cdetect -y 1
.venv/bin/python i2c_check.py
```

정상이면 메인 버스에 `0x70`과 MPU6050의 `0x68`(AD0가 HIGH면 `0x69`),
TCA 채널 0~3 각각에 ToF의 `0x29`가 보인다. 주소 스캔만으로는 VL53L5CX와
VL53L1X를 구분할 수 없으며 실제 모델 확인은 거리 코드 초기화 단계에서 수행된다.

## 4. 거리 측정

```bash
.venv/bin/python tof_distance.py
```

센서 없이 모의값을 보거나 CSV를 함께 저장할 수 있다. `--csv` 뒤에 경로를
생략하면 `hardware/logs/tof_날짜_시간.csv`가 자동 생성된다.

```bash
.venv/bin/python tof_distance.py --simulate
.venv/bin/python tof_distance.py --simulate --csv
.venv/bin/python tof_distance.py --csv my_tof_test.csv
```

VL53L5CX 초기화 때 펌웨어 전송 때문에 수 초가 걸릴 수 있다. 이후 전방·하향
VL53L5CX는 8x8 거리 배열과 최솟값을, 좌·우 VL53L1X는 단일 거리(mm)를
반복 출력한다. `Ctrl+C`로 종료한다.

센서는 유리, 검은색/반사 물체, 강한 햇빛, 비·안개, 장착 각도에 따라 오차나
무효값이 생길 수 있으므로 실제 보행 전에 실내 정지 시험부터 한다.

## 5. BLE 손목 진동 시험

ESP32 두 대에 `esp32_wrist/esp32_wrist.ino`를 업로드한다. 왼쪽 팔찌는
`LEFT_WRIST 1`, 오른쪽 팔찌는 `LEFT_WRIST 0`으로 각각 한 번씩 컴파일한다.
모터 제어 핀은 XIAO 보드 표기의 D2이다.

진동모터를 ESP32 GPIO에 직접 연결하지 않는다. D2는 MOSFET 또는 모터
드라이버의 입력에 연결하고, 모터에는 별도 전원과 플라이백 다이오드를 사용하며
ESP32와 모터 전원의 GND를 공통으로 연결한다.

라즈베리파이에서 다음을 실행한 뒤 `L` 또는 `R`을 입력한다. 선택한 팔찌가
한 번, 3초 동안 진동한다. `Q`를 입력하면 종료한다.

```bash
.venv/bin/python wrist_haptic_test.py
```

Linux에서 BLE 권한 오류가 발생하면 먼저 일반 사용자로 실행해 보고, 필요할 때만
BlueZ 서비스 상태와 사용자 권한을 확인한다. `sudo`로 실행하면 가상환경 패키지를
찾지 못할 수 있다.

### 오른쪽 팔찌만 사용하는 지도 길 안내

현재 왼쪽 팔찌는 비활성화하고 오른쪽 팔찌만 연결한다.
`esp32_wrist/esp32_wrist.ino`를 XIAO ESP32C3에 업로드한 뒤 Raspberry Pi에서
다음 게이트웨이를 실행한다. FastAPI 서버가 같은 Raspberry Pi에서 실행 중이면
기본 주소를 그대로 사용한다.

```bash
.venv/bin/python right_wrist_gateway.py
```

FastAPI 서버가 노트북 등 다른 장치에서 실행 중이면 그 장치의 IP를 지정한다.

```bash
.venv/bin/python right_wrist_gateway.py --server-url http://192.168.0.10:8000
```

게이트웨이는 `/api/haptics`를 0.5초마다 확인한다. 지도와 휴대폰 GPS에서 생성된
`RIGHT_WRIST` + `NAVIGATION` 명령만 오른쪽 ESP32에 보내며, `LEFT_WRIST`,
`BOTH_WRISTS`, 벨트 장애물 명령은 무시한다.

## 6. MPU6050 누적 회전각 시험

MPU6050을 움직이지 않은 상태로 실행한다. 시작할 때 약 1초 동안 자이로 오프셋을
보정한 후 Z축 회전각을 누적한다. 측정 중 `reset`을 입력한 경우에만 표시 각도가
0도로 돌아가고, `quit`으로 종료한다.

```bash
.venv/bin/python imu_rotation_test.py
```

모의 모드는 정지, 왼쪽 약 30도, 정지, 오른쪽 약 45도 패턴을 반복한다.
실제·모의 모드 모두 `reset`과 `quit` 명령을 사용할 수 있다.

```bash
.venv/bin/python imu_rotation_test.py --simulate
.venv/bin/python imu_rotation_test.py --simulate --csv
.venv/bin/python imu_rotation_test.py --csv my_imu_test.csv
```

센서 장착 방향 때문에 좌·우가 반대로 표시되면 다음처럼 실행한다.

```bash
.venv/bin/python imu_rotation_test.py --invert
```

MPU6050에는 지자기 센서가 없으므로 장시간 측정하면 자이로 적분 오차가 누적된다.
이 파일은 짧은 회전 시험용이다.

## 7. 전방·하향 ToF 계단 감지 시험

평지에 장치를 놓고 실행한다. 시작할 때 하향 VL53L5CX의 평지 거리를 자동으로
보정하고, 이후 3프레임 연속으로 조건을 만족해야 계단으로 표시한다.

```bash
.venv/bin/python stair_detection.py
```

모의 모드는 평지, 올라가는 계단, 평지, 내려가는 계단을 반복하며 동일한 판정
로직을 통과한다. 후보 판정과 3프레임 확인 후 최종 판정을 CSV에 모두 기록한다.

```bash
.venv/bin/python stair_detection.py --simulate
.venv/bin/python stair_detection.py --simulate --csv
.venv/bin/python stair_detection.py --csv my_stair_test.csv
```

- 하향 거리가 평지 기준보다 180mm 이상 증가: 내려가는 계단 감지
- 전방 8x8 배열의 아래쪽이 위쪽보다 180mm 이상 가까움: 올라가는 계단 감지
- 그 외: 평지

현재 기준값은 실내 시제품 시험을 위한 초기값이다. 센서 장착 높이·각도가 정해진
뒤 실제 평지와 계단 데이터를 기록해 조정해야 한다. 전방 센서 영상의 위아래가
반대로 장착됐다면 `stair_detection.py`의 상·하 배열 슬라이스를 서로 바꾼다.
