# WAYBAND 소프트웨어 구현 정리 (PPT 준비용)
---

## 1. 한 줄 요약

카카오 도보 경로 API로 경로를 자동 생성하고, 브라우저 GPS로 실시간 위치를 추적해 회전 지점에서 좌/우 팔찌 진동 명령을 만들어내는 FastAPI 서버 + 웹 화면입니다. 여기에 ToF 장애물 감지 시뮬레이터와, 시각장애인이 누르면 보호자 화면에 알림이 뜨는 위험 버튼 기능이 더해져 있습니다.

## 2. 시스템 구조

```
브라우저(보호자·장애인이 같이 보는 웹 화면)
   ├─ 카카오맵 JavaScript SDK로 지도 표시
   ├─ 브라우저 GPS로 현재 위치 추적
   └─ FastAPI 서버와 HTTP로 통신
        │
        ▼
FastAPI 서버 (wayband/)
   ├─ 카카오 REST API 호출 (장소 검색, 도보 경로)
   ├─ GPS 위치 ↔ 회전 지점 거리 계산 → 진동 명령 생성
   ├─ ToF 센서값 ↔ 경고/위험 판정 → 진동 명령 생성
   ├─ 위험 버튼 알림 상태 관리
   └─ 진동 명령을 순번 버퍼에 쌓아두고, 장치(ESP32 등)가 폴링해서 가져감
```

지금 단계에서는 GPS·ToF·위험 버튼 입력 모두 실제 하드웨어(벨트, 팔찌) 대신 **브라우저와 웹 화면의 시뮬레이터**로 대체되어 있습니다. 하드웨어가 연결되면 입력 소스만 교체하면 되도록, 진동 명령 생성 로직과 하드웨어 연동 부분을 분리해뒀습니다(자세한 내용은 `docs/HARDWARE_PROTOCOL.md`).

## 3. 화면 구성

화면은 사이드바 탭 2개로 나뉘어 있습니다(왼쪽에 세로로 긴 알약 모양 버튼).

- **경로** 탭: 출발지·도착지 검색 → 카카오 도보 경로 생성 → GPS 실시간 안내
- **센서** 탭: ToF 4개 센서값 시뮬레이터, 위험 버튼 시뮬레이터

탭과 무관하게 항상 떠 있는 요소:
- 상단 로고, 시스템 상태 표시
- 위험 알림이 활성화되면 화면 맨 위에 뜨는 빨간 배너
- 오른쪽 고정 영역: 지도, 진동 명령 로그

디자인은 밝은 크림색 배경에 반투명 유리 카드(`backdrop-filter: blur`)를 쓰는 톤이고, 제목은 Pretendard, 숫자(거리·좌표 등)는 IBM Plex Mono로 구분해서 표시합니다. (`web/index.html`, `web/styles.css`)

## 4. 기능별 상세

### 4.1 카카오 자동 경로 생성

- 장소 키워드 검색 → 후보 목록에서 사용자가 직접 선택(동명 장소 오류 방지)
- 카카오 공식 도보 경로 API(`/v2/routing/walk`)를 ACCESSIBLE/BROAD_FIRST/SHORTEST 세 가지 모드로 호출
- 응답의 `guidance` 문구를 좌회전/우회전/유턴/횡단보도/직진/도착으로 분류하고, 방향 표현이 없으면 경로 기하(방위각 차이)로 보조 추정
- 생성된 경로를 카카오맵 위에 폴리라인+마커로 표시

담당 코드: `wayband/kakao.py`, `wayband/route_parser.py`, `web/app.js`(`createRoute`, `drawRoute`)

### 4.2 GPS 실시간 안내

- 브라우저 GPS(`watchPosition`)로 현재 위치를 계속 서버에 전달
- 회전 지점 25m 반경에서 "준비" 진동(1회), 8m 반경에서 "지금 실행" 진동(3회) — 각각 한 번씩만 발생하도록 중복 방지
- GPS가 튀어 회전 지점을 지나쳐도 이후 안내가 막히지 않도록 지나간 지점은 자동으로 건너뜀
- 경로에서 3회 연속 벗어나면 양쪽 팔찌에 이탈 경고 진동
- 위치 정확도(accuracy)를 이탈 판정 여유 거리에 반영

담당 코드: `wayband/navigation.py`(`NavigationSession`), API의 `POST /api/navigation/{route_id}/location`

### 4.3 진동 명령 시스템

- 장치 종류에 안 묶이는 공통 진동 명령 포맷: 대상(왼쪽/오른쪽/양쪽 팔찌, 벨트 4방향), 패턴, 강도, 진동 횟수·간격
- 서버가 만든 명령은 순번이 매겨진 채로 최대 500개까지 버퍼에 쌓이고, 장치가 `GET /api/haptics?after_sequence=N`으로 새 명령만 가져가는 폴링 방식
- 화면의 "진동 명령 로그" 패널에서도 실시간으로 같은 명령을 확인 가능

담당 코드: `wayband/haptics.py`(`HapticCommand`, `CommandBuffer`)

### 4.4 ToF 장애물 감지

- 4방향(전방 좌/우, 좌/우측면) 센서값(mm)을 받아 위험/경고/해제 3단계로 판정
- 기준: 600mm 이하 위험, 1200mm 이하 경고, 1500mm 이상 해제
- 히스테리시스 적용: 한 번 경고/위험이 되면 해제 기준을 넘어야 CLEAR로 복귀 (경계값 근처에서 진동이 떨리듯 반복되는 것 방지)
- 상태가 실제로 바뀔 때만 새 진동 명령 생성

담당 코드: `wayband/hazard.py`(`HazardDetector`), API의 `POST /api/tof`

### 4.5 위험 버튼 알림

- 시각장애인 쪽 위험 버튼(지금은 화면 시뮬레이터)을 누르면 서버에 알림 1건이 등록됨
- 보호자 화면이 4초마다 폴링해서, 활성 알림이 있으면 화면 맨 위에 빨간 배너로 표시 (탭 상관없이 항상 보임)
- 버튼을 누른 순간 위치 권한이 있으면 GPS 좌표도 같이 전송
- "확인했어요"를 누르면 그 알림은 확인 처리되어 배너가 사라짐

담당 코드: `wayband/emergency.py`(`EmergencyCenter`), API의 `POST /api/emergency`, `GET /api/emergency`, `POST /api/emergency/{alert_id}/acknowledge`

### 4.6 경로 기록·경로 안내 모드 (코드는 있으나 현재 화면에서는 뺀 상태)

원래 "보호자가 실제로 걸으면서 좌회전/우회전/횡단보도/계단/도착 지점을 태깅해 `route_N.json`으로 저장하고, 나중에 그 경로를 불러와 안내받는" 기능을 만들었으나, 카카오 실시간 경로로 충분하다고 판단해 화면에서는 제외했습니다. 백엔드 로직(`wayband/recording.py`, `wayband/recorded_navigation.py`)과 테스트는 남아있어서, 필요하면 화면에 다시 연결만 하면 됩니다.

## 5. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 백엔드 | Python 3.11+, FastAPI, Uvicorn |
| 프론트엔드 | Vanilla JavaScript(프레임워크 없음), 카카오맵 JavaScript SDK |
| 폰트 | Pretendard(본문·제목), IBM Plex Mono(숫자) |
| 아이콘 | Tabler Icons 웹폰트 |
| 데이터 저장 | 서버 메모리(대부분), 경로 기록 완료분만 JSON 파일(`recorded_routes/`) |
| 테스트 | Python `unittest`, 네트워크 호출 없는 순수 로직 테스트 24개 |

## 6. API 엔드포인트 전체 목록

| 메서드 | 경로 | 기능 |
|---|---|---|
| GET | `/api/config` | 카카오 JS 키 등 공개 설정값 |
| GET | `/api/places` | 장소 검색 |
| POST | `/api/routes` | 카카오 자동 경로 생성 |
| GET | `/api/routes/{route_id}` | 생성된 경로 조회 |
| POST | `/api/navigation/{route_id}/location` | GPS 위치 갱신 → 진동 판정 |
| POST | `/api/tof` | ToF 4개 값 전달 → 경고/위험 판정 |
| GET | `/api/haptics` | 장치가 새 진동 명령 폴링 |
| POST | `/api/emergency` | 위험 버튼 트리거 |
| GET | `/api/emergency` | 현재 활성 알림 조회 |
| POST | `/api/emergency/{alert_id}/acknowledge` | 알림 확인 처리 |
| POST | `/api/recordings` | (화면 미연결) 경로 기록 시작 |
| GET | `/api/recordings` | (화면 미연결) 저장된 경로 목록 |
| POST | `/api/recordings/{id}/waypoints` | (화면 미연결) 지점 태깅 |
| POST | `/api/recordings/{id}/finish` | (화면 미연결) 기록 종료·저장 |
| POST | `/api/recorded-routes/{route_id}/start` | (화면 미연결) 기록 경로 안내 시작 |
| POST | `/api/recorded-routes/{route_id}/location` | (화면 미연결) 기록 경로 안내 중 위치 갱신 |

## 7. 아직 없는 것 (소프트웨어 기준)

- 벨트(라즈베리파이)의 실제 GPS/IMU를 서버가 직접 받는 경로 — 지금은 전부 브라우저 GPS로 대체
- 팔찌로 실제 BLE 진동 전송 — 지금은 HTTP 폴링 규격만 정의되어 있고, 실제 장치 펌웨어는 팀 하드웨어 파트 몫
- 위험 버튼 알림의 백그라운드 푸시(웹 푸시, 카카오 알림톡, SMS) — 지금은 보호자가 페이지를 열어둔 상태에서만 확인 가능
- 사용자 계정·로그인 — 보호자/장애인 구분 없이 고정된 한 쌍을 가정
- 데이터 영구 저장(DB) — 서버 재시작하면 진행 중이던 경로·알림은 사라짐 (완료된 경로 기록 JSON 파일만 예외)

## 8. 폴더 구조 요약

```
wayband/                   FastAPI 앱 코드
├─ api.py                  HTTP 엔드포인트 전체
├─ config.py                환경변수·거리 기준값
├─ kakao.py                카카오 장소·경로 API 클라이언트
├─ models.py                공용 도메인 모델(좌표, 장소, 경로)
├─ route_parser.py          카카오 응답 → 도메인 모델 변환·안내 분류
├─ navigation.py            GPS 기반 회전·이탈 판정
├─ hazard.py                ToF 상태·히스테리시스
├─ haptics.py                진동 명령 포맷과 폴링 버퍼
├─ emergency.py             위험 버튼 알림 상태 관리
├─ recording.py             (화면 미연결) 경로 기록 모드
├─ recorded_navigation.py   (화면 미연결) 기록 경로 안내
└─ service.py                기능 조립

web/                        웹 화면
├─ index.html
├─ styles.css
├─ app.js
└─ assets/logo.png

tests/                      단위 테스트 24개
docs/HARDWARE_PROTOCOL.md   장치 연동 규격 문서
```

---

이 문서는 소프트웨어 파트 기준으로만 정리했습니다. 하드웨어(벨트·팔찌 회로, 센서 배치, BLE 통신) 진행 상황은 별도로 정리가 필요합니다.
