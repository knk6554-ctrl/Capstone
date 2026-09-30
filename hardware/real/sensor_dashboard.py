"""WayBand sensor dashboard: ToF/IMU acquisition, judgement, and web UI.

Raspberry Pi:
    python sensor_dashboard.py

Laptop/demo mode:
    python sensor_dashboard.py --simulate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

HARDWARE_ROOT = Path(__file__).resolve().parents[1]
if str(HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(HARDWARE_ROOT))

from wayband_hw.core.detection import EnvironmentDetector
from wayband_hw.core.events import EventKind, WaybandEvent
from wayband_hw.core.patterns import pattern_for
from wayband_hw.drivers.ble_wrist import BleWristController
from wayband_hw.drivers.imu import Mpu6050Yaw

from config import Config
from control import front_is_blocked, plan_avoidance_angle
from sensors import TofRig


def usable(values: list[int | None]) -> list[int]:
    return [value for value in values if value is not None and 0 < value <= 4000]


def nearest(values: list[int | None]) -> int | None:
    valid = usable(values)
    return min(valid) if valid else None


def median(values: list[int | None]) -> int | None:
    valid = usable(values)
    return round(statistics.median(valid)) if valid else None


def stair_label(events: set[EventKind]) -> str:
    if EventKind.STAIR_UP in events:
        return "상행 계단 감지"
    if EventKind.STAIR_DOWN in events:
        return "하행 계단 감지"
    if EventKind.DOWN_DANGER in events:
        return "낙차 위험"
    return "계단 없음"


def avoidance_label(blocked: bool, angle: float | None) -> str:
    if not blocked:
        return "직진 가능"
    if angle is None:
        return "통로 없음 · 정지"
    if angle < 0:
        return "좌측으로 피함"
    if angle > 0:
        return "우측으로 피함"
    return "직진 가능"


@dataclass
class SharedState:
    payload: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, payload: dict[str, Any]) -> None:
        with self.lock:
            self.payload = payload

    def get(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.payload)


class DemoRig:
    """Repeatable temporary values for a presentation without hardware."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.started = time.monotonic()

    def start(self) -> None:
        return None

    def snapshot(self) -> tuple[list[int], list[int], int, int, float, float, str]:
        phase = int((time.monotonic() - self.started) / 5) % 5
        front = [1800 + ((row + col) % 5) * 50 for row in range(8) for col in range(8)]
        down = [700 + ((row + col) % 4) * 10 for row in range(8) for col in range(8)]
        left, right, angle, rate = 850, 1180, 0.0, 0.0
        name = "정상 보행"

        if phase == 1:  # obstacle on left -> escape right
            name = "장애물 · 우측 회피"
            for row in range(2, 7):
                for col in range(0, 4):
                    front[row * 8 + col] = 320 + row * 30 + col * 20
            angle, rate = 22.5, 3.1
        elif phase == 2:  # obstacle on right -> escape left
            name = "장애물 · 좌측 회피"
            for row in range(2, 7):
                for col in range(4, 8):
                    front[row * 8 + col] = 330 + row * 30 + (7 - col) * 20
            angle, rate = -22.5, -3.1
        elif phase == 3:  # upper/lower front difference -> stair up
            name = "상행 계단"
            front = [1300] * 32 + [750] * 32
        elif phase == 4:  # farther ground -> stair down
            name = "하행 계단"
            down = [950] * 64

        return front, down, left, right, angle, rate, name

    def close(self) -> None:
        return None


def make_payload(
    cfg: Config,
    detector: EnvironmentDetector,
    front: list[int | None],
    down: list[int | None],
    left_mm: int | None,
    right_mm: int | None,
    angle: float,
    rate: float,
    source: str,
) -> dict[str, Any]:
    events = detector.evaluate(front, down)
    kinds = {event.kind for event in events}
    # A stair profile can also be close to the front sensor.  Safety events
    # take priority so the UI does not misleadingly call stairs an obstacle.
    stair_or_drop = bool(kinds & {EventKind.STAIR_UP, EventKind.STAIR_DOWN, EventKind.DOWN_DANGER})
    blocked = cfg.enable_front and front_is_blocked(front, cfg.front_warning_mm) and not stair_or_drop
    avoid_angle = plan_avoidance_angle(
        front,
        left_mm,
        right_mm,
        horizontal_fov_degrees=cfg.tof_horizontal_fov_degrees,
        obstacle_mm=cfg.front_warning_mm,
        side_clear_mm=cfg.side_clear_mm,
        minimum_corridor_width_mm=cfg.minimum_corridor_width_mm,
    ) if blocked else 0.0
    obstacle = "장애물 감지" if blocked or EventKind.FRONT_DANGER in kinds else "장애물 없음"
    stairs = stair_label(kinds)
    avoidance = avoidance_label(blocked, avoid_angle)

    levels = ["normal", "normal", "normal", "normal"]
    if blocked:
        levels[0] = "danger"
    if stairs != "계단 없음":
        levels[1] = "danger" if "낙차" in stairs else "warning"
    if left_mm is not None and left_mm <= cfg.side_clear_mm:
        levels[2] = "warning"
    if right_mm is not None and right_mm <= cfg.side_clear_mm:
        levels[3] = "warning"

    return {
        "timestamp": time.time(),
        "source": source,
        "front": front,
        "front_enabled": cfg.enable_front,
        "down": down,
        "front_nearest_mm": nearest(front),
        "down_median_mm": median(down),
        "left_mm": left_mm,
        "right_mm": right_mm,
        "angle_deg": round(angle, 1),
        "rate_dps": round(rate, 1),
        "imu_bias_dps": round(getattr(getattr(sensor_loop, "imu", None), "bias_dps", 0.0), 2),
        "obstacle": obstacle,
        "stairs": stairs,
        "avoidance": avoidance,
        "avoidance_angle_deg": avoid_angle,
        "levels": levels,
        "counts": {
            "normal": levels.count("normal"),
            "warning": levels.count("warning"),
            "danger": levels.count("danger"),
        },
    }


def _web_dashboard_payload(payload: dict[str, Any], bias_dps: float) -> dict[str, Any]:
    """make_payload()가 만든 이 파일 전용 모양을 web/app.js의 renderSensorDashboard()가
    그대로 그릴 수 있는 모양으로 재구성한다(hardware/real/main.py의 _web_dashboard_payload와
    같은 목적 — 여기서는 이미 계산된 make_payload()의 counts/levels를 재사용한다).
    """

    def grid(flat: list) -> list[list]:
        return [flat[row * 8 : row * 8 + 8] for row in range(8)]

    counts = payload["counts"]
    angle = payload["angle_deg"]
    direction = "LEFT" if angle < -0.5 else "RIGHT" if angle > 0.5 else "NONE"
    return {
        "stats": {
            "leftSideMm": payload["left_mm"],
            "rightSideMm": payload["right_mm"],
            "rotationDeg": angle,
            "gyroZOffsetDegPerSec": round(bias_dps, 2),
            "gyroZFinalDegPerSec": payload["rate_dps"],
        },
        "statusSummary": [
            {"level": "good", "label": "정상", "count": counts.get("normal", 0)},
            {"level": "warning", "label": "경고", "count": counts.get("warning", 0)},
            {"level": "critical", "label": "위험", "count": counts.get("danger", 0)},
        ],
        "imu": {"direction": direction, "angleDeg": angle},
        "tof": {"front": grid(payload["front"]), "down": grid(payload["down"])},
    }


def _push_web_dashboard(server_url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{server_url}/api/sensors/dashboard",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2):
        pass


def sensor_loop(args: argparse.Namespace, state: SharedState, stop: threading.Event) -> None:
    cfg = Config(
        baseline_down_mm=args.baseline_down_mm,
        imu_invert=args.invert_imu,
        enable_front=args.enable_front,
    )
    detector = EnvironmentDetector(
        cfg.baseline_down_mm,
        obstacle_mm=cfg.front_warning_mm,
        drop_delta_mm=cfg.down_drop_delta_mm,
        rise_delta_mm=cfg.stair_rise_delta_mm,
    )
    # One confirmed frame is easier to understand during a live demonstration.
    detector.gate.required = 1
    rig: Any = DemoRig(cfg) if args.simulate else TofRig(cfg)
    bus = None
    imu = None
    wrists = BleWristController(simulate=args.simulate_ble)
    ble_loop = asyncio.new_event_loop()
    last_haptic: dict[EventKind, float] = {}

    def send_safety_haptic(payload: dict[str, Any]) -> str:
        kind: EventKind | None = None
        detail = ""
        distance: int | None = None
        if payload["stairs"] == "낙차 위험":
            kind, detail, distance = EventKind.DOWN_DANGER, "낙차 위험", payload["down_median_mm"]
        elif payload["stairs"] == "하행 계단 감지":
            kind, detail, distance = EventKind.STAIR_DOWN, "하행 계단", payload["down_median_mm"]
        elif payload["stairs"] == "상행 계단 감지":
            kind, detail, distance = EventKind.STAIR_UP, "상행 계단", payload["front_nearest_mm"]
        elif payload["obstacle"] == "장애물 감지":
            kind, detail, distance = EventKind.FRONT_DANGER, "전방 장애물", payload["front_nearest_mm"]

        if kind is None:
            return "대기 · 위험 없음"
        event = WaybandEvent(kind, "SENSOR_DASHBOARD", detail, distance)
        pattern = pattern_for(event)
        now = time.monotonic()
        cooldown = max(pattern.repeat_after_ms / 1000.0, 0.7)
        if now - last_haptic.get(kind, -1e9) < cooldown:
            return f"{detail} 패턴 재알림 대기"
        try:
            ble_loop.run_until_complete(wrists.send(pattern))
            last_haptic[kind] = now
            return f"{detail} 진동 전송 완료"
        except Exception as exc:
            # A disconnected bracelet must not stop sensor monitoring.
            return f"BLE 전송 실패: {exc}"

    try:
        rig.start()
        if not args.simulate:
            from smbus2 import SMBus

            bus = SMBus(cfg.i2c_bus)
            imu = Mpu6050Yaw(bus, cfg.imu_address, cfg.imu_invert)
            print("IMU 보정 중입니다. 장치를 움직이지 마세요.")
            imu.initialize()
        sensor_loop.imu = imu
        last_dashboard_push = 0.0
        web_dashboard_status = "아직 전송 안 함"

        while not stop.is_set():
            if args.simulate:
                front, down, left, right, angle, rate, source = rig.snapshot()
            else:
                front, down, left, right = rig.snapshot()
                angle, rate = imu.update()
                source = "실제 센서"
            payload = make_payload(cfg, detector, front, down, left, right, angle, rate, source)
            payload["haptic_status"] = send_safety_haptic(payload)

            now = time.monotonic()
            if not args.no_web_dashboard and now - last_dashboard_push >= 0.5:
                last_dashboard_push = now
                web_payload = _web_dashboard_payload(
                    payload, getattr(imu, "bias_dps", 0.0)
                )
                try:
                    _push_web_dashboard(args.server_url, web_payload)
                    web_dashboard_status = f"정상 전송 ({time.strftime('%H:%M:%S')})"
                except (URLError, TimeoutError, OSError) as exc:
                    web_dashboard_status = f"전송 실패: {exc}"
                    print(f"웹 대시보드 전송 실패(계속 진행합니다): {exc}")
            payload["web_dashboard_status"] = web_dashboard_status

            state.set(payload)
            stop.wait(args.interval)
    except Exception as exc:
        state.set({"error": str(exc), "timestamp": time.time()})
        print(f"센서 오류: {exc}")
    finally:
        rig.close()
        if bus is not None:
            bus.close()
        try:
            if wrists.clients or args.simulate_ble:
                ble_loop.run_until_complete(wrists.stop())
            ble_loop.run_until_complete(wrists.close())
        except Exception:
            pass
        ble_loop.close()


HTML = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WayBand 센서 대시보드</title><style>
:root{font-family:Arial,"Noto Sans KR",sans-serif;color:#19313d;background:#f5f8f5}*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:12px;align-items:start}.live{padding:8px 12px;border-radius:999px;background:#e3f3ed;color:#176b55;font-weight:700}.muted{color:#68777d}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.card,.panel,.decision{background:#fff;border:1px solid #d8e0dc;border-radius:16px;padding:18px}.card span,.decision span{display:block;text-align:center;font-size:14px}.card strong{display:block;text-align:center;font:700 27px monospace;margin-top:8px}.unit{font:12px Arial;color:#87918e}.decisions{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}.decision strong{display:block;text-align:center;margin-top:8px;font-size:20px}.decision.danger{border-color:#ee6a55;background:#fff2ef}.decision.warning{border-color:#e69a32;background:#fff8e9}.decision.good{border-color:#56a88f;background:#eff9f5}.content{display:grid;grid-template-columns:210px 1fr 1fr;gap:14px}.counts{display:flex;gap:7px;flex-wrap:wrap}.pill{padding:9px 12px;border-radius:999px;border:1px solid}.normal{color:#18705a;background:#edf8f4}.warning{color:#b05b00;background:#fff5e5}.danger{color:#c62f2f;background:#fff0ef}.gauge{height:120px;margin-top:24px;display:grid;place-items:center;background:conic-gradient(from 270deg,#2b806a 0 28%,#dce3df 28% 50%,transparent 50%);border-radius:120px 120px 0 0}.gauge strong{font:700 22px monospace}.grid{display:grid;grid-template-columns:repeat(8,1fr);gap:5px;margin-top:14px}.cell{aspect-ratio:1.35;display:grid;place-items:center;border-radius:5px;color:#fff;font:700 11px monospace;background:#dd760d}.cell.near{background:#de3f2c}.cell.none{background:#9ba6a2}.foot{margin-top:18px;padding-top:16px;border-top:1px solid #dde4e0;font-size:13px;color:#74807c}@media(max-width:850px){.cards{grid-template-columns:repeat(2,1fr)}.content{grid-template-columns:1fr}.decisions{grid-template-columns:1fr}.cell{font-size:9px}} </style></head>
<body><main><div class="top"><div><h1>센서 데이터 대시보드</h1><p class="muted">ToF·IMU 센서값과 실시간 안전 판정을 확인합니다.</p></div><div id="live" class="live">연결 중</div></div>
<section class="cards"><div class="card"><span>좌측 측면 거리</span><strong id="left">-</strong></div><div class="card"><span>우측 측면 거리</span><strong id="right">-</strong></div><div class="card"><span>측정 회전각</span><strong id="angle">-</strong></div><div class="card"><span>회전 각속도</span><strong id="rate">-</strong></div></section>
<section class="decisions"><div id="obstacleCard" class="decision good"><span>전방 판정</span><strong id="obstacle">-</strong></div><div id="stairCard" class="decision good"><span>계단·낙차 판정</span><strong id="stairs">-</strong></div><div id="avoidCard" class="decision good"><span>회피 결정</span><strong id="avoidance">-</strong></div></section>
<section class="content"><div class="panel"><h3>센서 상태 요약</h3><div class="counts"><b class="pill normal">정상 <i id="normal">0</i></b><b class="pill warning">경고 <i id="warning">0</i></b><b class="pill danger">위험 <i id="danger">0</i></b></div><div class="gauge"><strong id="gauge">0°</strong></div><p id="source" class="muted"></p></div><div id="frontPanel" class="panel"><h3>전방 ToF 8×8 <small>mm</small></h3><div id="front" class="grid"></div></div><div class="panel"><h3>하향 ToF 8×8 <small>mm</small></h3><div id="down" class="grid"></div></div></section>
<footer class="foot"><b>안전 및 접근성 안내</b><p>본 시스템은 프로토타입 연구용이며 흰지팡이 및 안내견 등 표준 보행 보조 수단을 보완합니다.</p></footer></main>
<script>
const $=id=>document.getElementById(id), value=(v,u)=>v==null?'측정 불가':`${v}<small class="unit"> ${u}</small>`;
function grid(id,values){$(id).replaceChildren(...values.map(v=>{const e=document.createElement('div');e.className='cell '+(v==null?'none':v<=1000?'near':'');e.textContent=v??'--';return e}))}
function tone(id,text){const e=$(id);e.className='decision '+(text.includes('감지')||text.includes('위험')||text.includes('정지')?'danger':text.includes('계단')&&!text.includes('없음')?'warning':'good')}
async function update(){try{const r=await fetch('/api/sensors',{cache:'no-store'}),d=await r.json();if(d.error)throw Error(d.error);$('left').innerHTML=value(d.left_mm,'mm');$('right').innerHTML=value(d.right_mm,'mm');$('angle').innerHTML=value(d.angle_deg,'°');$('rate').innerHTML=value(d.rate_dps,'°/s');['obstacle','stairs','avoidance'].forEach(k=>$(k).textContent=d[k]);tone('obstacleCard',d.obstacle);tone('stairCard',d.stairs);tone('avoidCard',d.avoidance);Object.entries(d.counts).forEach(([k,v])=>$(k).textContent=v);$('gauge').textContent=`${d.angle_deg>0?'우회전 ':d.angle_deg<0?'좌회전 ':''}${Math.abs(d.angle_deg)}°`;$('source').textContent=`${d.source} · ${new Date(d.timestamp*1000).toLocaleTimeString()}`;$('frontPanel').hidden=!d.front_enabled;if(d.front_enabled)grid('front',d.front);grid('down',d.down);$('live').textContent='● 실시간';}catch(e){$('live').textContent='연결 오류';$('live').className='live danger';}}
setInterval(update,250);update();</script></body></html>'''


def handler_for(state: SharedState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/sensors":
                body = json.dumps(state.get(), ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body = HTML.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: Any) -> None:
            return None

    return Handler


def terminal_value(value: Any, suffix: str = "") -> str:
    return "측정 불가" if value is None else f"{value}{suffix}"


def render_terminal(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"WayBand 센서 초기화 중\n\n{payload['error']}"

    def grid(values: list[int | None]) -> str:
        rows = []
        for row in range(8):
            cells = values[row * 8:(row + 1) * 8]
            rows.append("  ".join("  --" if value is None else f"{value:4d}" for value in cells))
        return "\n".join(rows)

    lines = [
        "WayBand 실시간 센서 모니터  (Ctrl+C 종료)",
        "=" * 72,
        f"입력: {payload['source']}  |  갱신: {time.strftime('%H:%M:%S')}",
        "",
        f"좌측 {terminal_value(payload['left_mm'], ' mm'):>12}   "
        f"우측 {terminal_value(payload['right_mm'], ' mm'):>12}   "
        f"회전각 {terminal_value(payload['angle_deg'], '°'):>10}   "
        f"각속도 {terminal_value(payload['rate_dps'], '°/s'):>10}",
        "",
        f"[장애물] {payload['obstacle']}",
        f"[계단/낙차] {payload['stairs']}",
        f"[회피 결정] {payload['avoidance']}"
        + (f" ({payload['avoidance_angle_deg']:+.1f}°)" if payload["avoidance_angle_deg"] not in (None, 0) else ""),
        f"[팔찌 진동] {payload.get('haptic_status', '연결 준비 중')}",
        f"[웹 대시보드] {payload.get('web_dashboard_status', '아직 전송 안 함')}",
    ]
    if payload.get("front_enabled", True):
        lines.extend(("", "전방 ToF 8×8 (mm)", grid(payload["front"])))
    lines.extend((
        "",
        "하향 ToF 8×8 (mm)",
        grid(payload["down"]),
    ))
    return "\n".join(lines)


def run_terminal(state: SharedState, stop: threading.Event) -> None:
    try:
        while True:
            # ANSI home+clear works in the Raspberry Pi terminal and avoids
            # continuously appending hundreds of 8x8 rows to its scrollback.
            print("\033[2J\033[H" + render_terminal(state.get()), end="", flush=True)
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n센서 모니터를 종료합니다.")
    finally:
        stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="WayBand 실시간 센서 웹 대시보드")
    parser.add_argument("--simulate", action="store_true", help="하드웨어 없이 임시값 순환")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--baseline-down-mm", type=int, default=700)
    parser.add_argument("--invert-imu", action="store_true")
    parser.add_argument("--enable-front", action="store_true", help="교체한 전방 VL53L5CX(CH1)를 다시 사용")
    parser.add_argument("--terminal", action="store_true", help="웹 없이 현재 터미널에 표시")
    parser.add_argument("--simulate-ble", action="store_true", help="실제 팔찌 없이 진동 전송 시험")
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000",
        help="WAYBAND 지도 서버 주소 — 0.5초마다 이 서버의 /api/sensors/dashboard로 센서값을 올린다",
    )
    parser.add_argument(
        "--no-web-dashboard",
        action="store_true",
        help="지도 서버로 센서값을 전송하지 않음(기본은 전송함)",
    )
    args = parser.parse_args()

    state = SharedState({"error": "센서 초기화 중입니다."})
    stop = threading.Event()
    worker = threading.Thread(target=sensor_loop, args=(args, state, stop), daemon=True)
    worker.start()
    if args.terminal:
        run_terminal(state, stop)
        worker.join(timeout=2)
        return

    server = ThreadingHTTPServer((args.host, args.port), handler_for(state))
    print(f"센서 대시보드: http://127.0.0.1:{args.port} ({'임시값' if args.simulate else '실제 센서'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n센서 대시보드를 종료합니다.")
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=2)


sensor_loop.imu = None

if __name__ == "__main__":
    main()
