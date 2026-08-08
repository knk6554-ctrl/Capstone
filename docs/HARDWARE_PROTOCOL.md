# WAYBAND 하드웨어 연동 프로토콜

이 문서는 특정 ESP32 보드, ToF 모델, BLE 라이브러리에 종속되지 않는 서버 경계 규격입니다. 실제 핀 번호와 통신 코드는 팀의 회로·부품이 정해진 뒤 이 규격에 맞춰 구현하세요.

## 안전 우선 구조

장애물은 서버가 아니라 벨트 MCU에서 먼저 판정해야 합니다.

```text
ToF 4개 → 벨트 MCU → 즉시 로컬 진동
                    └→ 서버에 상태 전송(화면 표시·기록)

서버 GPS 판정 → 진동 명령 큐 → ESP32 게이트웨이 → 좌/우 팔찌
```

Wi-Fi, 휴대전화, 서버가 끊겨도 ToF 장애물 진동은 유지되어야 합니다. 센서 초기화 실패, 값 범위 초과, 배터리 부족도 정상 상태와 다른 고유 진동으로 알리는 편이 안전합니다.

## ToF 텔레메트리 전송

`POST /api/tof`

```json
{
  "gateway_id": "belt-01",
  "front_left_mm": 850,
  "front_right_mm": 2100,
  "left_side_mm": 1800,
  "right_side_mm": 2400
}
```

응답 예시:

```json
{
  "gatewayId": "belt-01",
  "sensors": {
    "FRONT_LEFT": { "distanceMm": 850, "level": "WARNING" },
    "FRONT_RIGHT": { "distanceMm": 2100, "level": "CLEAR" },
    "LEFT_SIDE": { "distanceMm": 1800, "level": "CLEAR" },
    "RIGHT_SIDE": { "distanceMm": 2400, "level": "CLEAR" }
  },
  "commands": []
}
```

기본 임계값은 위험 600mm 이하, 경고 1200mm 이하, 해제 1500mm 이상입니다. 0 또는 4000mm 초과는 `INVALID`로 취급합니다. 실제 임계값은 보행 속도, 센서 시야각, 장착 높이와 사용자 시험으로 정하세요.

## 진동 명령 가져오기

게이트웨이는 마지막으로 처리한 순번 이후의 명령을 요청합니다.

```http
GET /api/haptics?after_sequence=42&limit=20
```

응답 예시:

```json
{
  "commands": [
    {
      "sequence": 43,
      "commandId": "uuid",
      "createdAt": "2026-08-03T12:00:00+00:00",
      "target": "LEFT_WRIST",
      "pattern": "TURN_NOW",
      "source": "NAVIGATION",
      "message": "왼쪽으로 이동",
      "intensity": 0.9,
      "pulseCount": 3,
      "pulseOnMs": 220,
      "pulseOffMs": 180
    }
  ],
  "lastSequence": 43
}
```

게이트웨이는 명령을 실행한 뒤 `lastSequence`를 비휘발성 저장소 또는 안전한 런타임 상태에 기억합니다. 같은 `commandId`를 이미 실행했다면 다시 울리지 않아야 합니다.

## 경로 기록 파일(route_N.json)

`POST /api/recordings/{id}/finish`가 성공하면 `recorded_routes/route_<id>.json`이 생성됩니다. 라즈베리파이 벨트가 안내 모드에서 그대로 읽어갈 수 있도록 평평한 구조를 유지합니다.

```json
{
  "route_id": 1,
  "name": "정문에서 공학관",
  "waypoints": [
    { "type": "start", "lat": 37.12345, "lon": 127.12345 },
    { "type": "left_turn", "lat": 37.1238, "lon": 127.1237 },
    { "type": "crosswalk", "lat": 37.124, "lon": 127.1239 },
    { "type": "destination", "lat": 37.1242, "lon": 127.1241 }
  ]
}
```

`type`은 `start`, `left_turn`, `right_turn`, `crosswalk`, `stairs`, `destination` 중 하나입니다. 이 서버는 아직 이 파일을 기준으로 실시간 판단(다음 waypoint까지 거리 계산, BLE 명령 전송)을 수행하지 않습니다. 현재는 기록만 담당하며, 실시간 판단은 벨트(라즈베리파이) 또는 이후 서버 확장에서 구현해야 합니다.

## 장치 구현 권장 사항

- 명령 생성 시각이 너무 오래된 명령은 버립니다. 서버와 MCU의 시계 동기화가 어렵다면 수신 후 TTL을 별도 필드로 확장하세요.
- `source=TOF`는 서버 명령보다 MCU의 로컬 장애물 판정을 우선합니다.
- 통신이 끊기면 마지막 명령을 무한 반복하지 않습니다.
- 모터 고착을 막기 위해 한 번의 연속 구동 시간에 상한을 둡니다.
- 팔찌 좌우 페어링이 바뀌지 않도록 장치 ID와 물리 라벨을 함께 사용합니다.
- 서버 API에는 장치별 인증 토큰과 TLS를 추가한 뒤 외부 네트워크에 노출합니다.
- 실제 BLE를 쓸 경우 게이트웨이→팔찌 패킷에 `commandId`, `target`, `pulseCount`, `pulseOnMs`, `pulseOffMs`, 체크섬을 포함하는 것이 좋습니다.
