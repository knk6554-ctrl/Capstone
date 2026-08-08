"use strict";

const state = {
  map: null,
  routeLine: null,
  markers: [],
  userMarker: null,
  selected: { start: null, destination: null },
  route: null,
  watchId: null,
  hapticLogStarted: false,
  recording: null,
  recordingWatchId: null,
  recordingLastPosition: null,
  recordingMarkers: [],
  recordingLine: null,
  recordingPath: [],
  guided: null,
  guidedWatchId: null,
  guidedMarkers: [],
  guidedLine: null,
};

const RECORD_TAG_LABELS = {
  start: "시작",
  left_turn: "좌회전",
  right_turn: "우회전",
  crosswalk: "횡단보도",
  stairs: "계단",
  destination: "도착",
};

const elements = {
  systemStatus: document.querySelector("#system-status"),
  createRoute: document.querySelector("#create-route"),
  routeMode: document.querySelector("#route-mode"),
  routeMessage: document.querySelector("#route-message"),
  routeSummary: document.querySelector("#route-summary"),
  summaryDistance: document.querySelector("#summary-distance"),
  summaryTime: document.querySelector("#summary-time"),
  summarySteps: document.querySelector("#summary-steps"),
  mapCaption: document.querySelector("#map-caption"),
  directions: document.querySelector("#directions"),
  startNavigation: document.querySelector("#start-navigation"),
  stopNavigation: document.querySelector("#stop-navigation"),
  nextGuidance: document.querySelector("#next-guidance"),
  hapticLog: document.querySelector("#haptic-log"),
  sensorStatus: document.querySelector("#sensor-status"),
  recordName: document.querySelector("#record-name"),
  recordStart: document.querySelector("#record-start"),
  recordSetup: document.querySelector("#record-setup"),
  recordActive: document.querySelector("#record-active"),
  recordGpsStatus: document.querySelector("#record-gps-status"),
  recordPoints: document.querySelector("#record-points"),
  recordCount: document.querySelector("#record-count"),
  recordSave: document.querySelector("#record-save"),
  recordMessage: document.querySelector("#record-message"),
  recordBadge: document.querySelector("#record-recording-badge"),
  guidedSelect: document.querySelector("#guided-route-select"),
  guidedRefresh: document.querySelector("#guided-refresh"),
  guidedStart: document.querySelector("#guided-start"),
  guidedStop: document.querySelector("#guided-stop"),
  guidedNext: document.querySelector("#guided-next"),
};

function setStatus(message, isError = false) {
  elements.systemStatus.textContent = message;
  elements.systemStatus.style.color = isError ? "var(--danger)" : "var(--yellow)";
}

function switchTab(tabName) {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `tab-${tabName}`);
  });
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `요청 실패 (${response.status})`);
  }
  return payload;
}

function loadKakaoMap(javascriptKey) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(
      javascriptKey,
    )}&autoload=false`;
    script.onload = () => {
      window.kakao.maps.load(() => {
        state.map = new window.kakao.maps.Map(document.querySelector("#map"), {
          center: new window.kakao.maps.LatLng(37.5049, 126.9494),
          level: 5,
        });
        state.map.addControl(
          new window.kakao.maps.ZoomControl(),
          window.kakao.maps.ControlPosition.RIGHT,
        );
        resolve();
      });
    };
    script.onerror = () => reject(new Error("카카오 지도 SDK를 불러오지 못했습니다."));
    document.head.appendChild(script);
  });
}

async function initialize() {
  try {
    const config = await api("/api/config");
    await loadKakaoMap(config.kakaoJavascriptKey);
    bindEvents();
    setStatus("지도 준비 완료");
  } catch (error) {
    setStatus(error.message, true);
    elements.routeMessage.textContent = error.message;
  }
}

function bindEvents() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  document.querySelectorAll("[data-search]").forEach((button) => {
    button.addEventListener("click", () => searchPlaces(button.dataset.search));
  });
  ["start", "destination"].forEach((kind) => {
    document.querySelector(`#${kind}-query`).addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        searchPlaces(kind);
      }
    });
  });
  elements.createRoute.addEventListener("click", createRoute);
  elements.startNavigation.addEventListener("click", startNavigation);
  elements.stopNavigation.addEventListener("click", stopNavigation);
  document.querySelector("#send-tof").addEventListener("click", sendTofReadings);

  elements.recordStart.addEventListener("click", startRecording);
  elements.recordSave.addEventListener("click", finishRecording);
  document.querySelectorAll("[data-record-tag]").forEach((button) => {
    button.addEventListener("click", () => tagRecordingWaypoint(button.dataset.recordTag));
  });

  elements.guidedRefresh.addEventListener("click", loadSavedRoutes);
  elements.guidedSelect.addEventListener("change", () => {
    elements.guidedStart.disabled = !elements.guidedSelect.value;
  });
  elements.guidedStart.addEventListener("click", startGuidedNavigation);
  elements.guidedStop.addEventListener("click", stopGuidedNavigation);
  loadSavedRoutes();
}

async function searchPlaces(kind) {
  const queryInput = document.querySelector(`#${kind}-query`);
  const results = document.querySelector(`#${kind}-results`);
  const query = queryInput.value.trim();
  if (!query) {
    results.textContent = "검색어를 입력하세요.";
    return;
  }

  results.textContent = "검색 중…";
  try {
    let url = `/api/places?query=${encodeURIComponent(query)}`;
    if (kind === "destination" && state.selected.start) {
      const point = state.selected.start.coordinate;
      url += `&center_longitude=${point.longitude}&center_latitude=${point.latitude}`;
    }
    const payload = await api(url);
    renderPlaceResults(kind, payload.places);
  } catch (error) {
    results.textContent = error.message;
  }
}

function renderPlaceResults(kind, places) {
  const results = document.querySelector(`#${kind}-results`);
  results.replaceChildren();
  if (!places.length) {
    results.textContent = "검색 결과가 없습니다.";
    return;
  }
  places.forEach((place) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "place-result";
    const name = document.createElement("strong");
    name.textContent = place.name;
    const address = document.createElement("span");
    address.textContent = place.roadAddress || place.address || "주소 정보 없음";
    button.append(name, address);
    button.addEventListener("click", () => selectPlace(kind, place));
    results.appendChild(button);
  });
}

function selectPlace(kind, place) {
  state.selected[kind] = place;
  const selected = document.querySelector(`#${kind}-selected`);
  selected.textContent = `${place.name} · ${place.roadAddress || place.address}`;
  selected.classList.add("is-selected");
  document.querySelector(`#${kind}-results`).replaceChildren();
  elements.createRoute.disabled = !(state.selected.start && state.selected.destination);

  const position = new window.kakao.maps.LatLng(
    place.coordinate.latitude,
    place.coordinate.longitude,
  );
  state.map.panTo(position);
}

function placeRequest(place) {
  return {
    id: place.id,
    name: place.name,
    address: place.address,
    road_address: place.roadAddress,
    phone: place.phone,
    place_url: place.placeUrl,
    coordinate: place.coordinate,
  };
}

async function createRoute() {
  elements.createRoute.disabled = true;
  elements.routeMessage.textContent = "편안한 보행 경로를 찾고 있습니다…";
  try {
    const route = await api("/api/routes", {
      method: "POST",
      body: JSON.stringify({
        start: placeRequest(state.selected.start),
        destination: placeRequest(state.selected.destination),
        route_mode: elements.routeMode.value,
      }),
    });
    state.route = route;
    drawRoute(route);
    renderRoute(route);
    elements.startNavigation.disabled = false;
    elements.routeMessage.textContent = "경로를 만들었습니다.";
    setStatus("경로 준비 완료");
  } catch (error) {
    elements.routeMessage.textContent = error.message;
    setStatus("경로 생성 실패", true);
  } finally {
    elements.createRoute.disabled = false;
  }
}

function drawRoute(route) {
  if (state.routeLine) state.routeLine.setMap(null);
  state.markers.forEach((marker) => marker.setMap(null));
  state.markers = [];

  const path = route.path.map(
    (point) => new window.kakao.maps.LatLng(point.latitude, point.longitude),
  );
  state.routeLine = new window.kakao.maps.Polyline({
    map: state.map,
    path,
    strokeWeight: 7,
    strokeColor: "#087f75",
    strokeOpacity: 0.95,
    strokeStyle: "solid",
  });

  [route.start, route.destination].forEach((place) => {
    state.markers.push(
      new window.kakao.maps.Marker({
        map: state.map,
        position: new window.kakao.maps.LatLng(
          place.coordinate.latitude,
          place.coordinate.longitude,
        ),
      }),
    );
  });

  const bounds = new window.kakao.maps.LatLngBounds();
  path.forEach((point) => bounds.extend(point));
  state.map.setBounds(bounds, 70, 70, 70, 70);
}

function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes}분`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분`;
}

function renderRoute(route) {
  elements.routeSummary.hidden = false;
  elements.summaryDistance.textContent = `${route.totalDistanceMeters.toLocaleString()} m`;
  elements.summaryTime.textContent = formatDuration(route.totalTimeSeconds);
  elements.summarySteps.textContent = `${route.steps.length}개`;
  elements.mapCaption.textContent = `${route.start.name} → ${route.destination.name}`;
  elements.directions.replaceChildren();
  route.steps.forEach((step) => {
    const item = document.createElement("li");
    const maneuver = document.createElement("strong");
    maneuver.textContent = `[${step.maneuver}] `;
    item.append(maneuver, step.guidance || `${step.distanceMeters}m 이동`);
    elements.directions.appendChild(item);
  });
  elements.nextGuidance.textContent = "GPS 안내를 시작하면 다음 회전까지 거리를 표시합니다.";
}

function startNavigation() {
  if (!state.route || !navigator.geolocation) {
    elements.nextGuidance.textContent = "이 브라우저에서는 위치 기능을 사용할 수 없습니다.";
    return;
  }
  state.watchId = navigator.geolocation.watchPosition(
    updateLocation,
    (error) => {
      elements.nextGuidance.textContent = `위치 오류: ${error.message}`;
      setStatus("GPS 오류", true);
    },
    { enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 },
  );
  elements.startNavigation.disabled = true;
  elements.stopNavigation.disabled = false;
  setStatus("GPS 안내 중");
}

function stopNavigation() {
  if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
  state.watchId = null;
  elements.startNavigation.disabled = !state.route;
  elements.stopNavigation.disabled = true;
  setStatus("GPS 안내 중지");
}

async function updateLocation(position) {
  const location = {
    longitude: position.coords.longitude,
    latitude: position.coords.latitude,
    accuracy_meters: position.coords.accuracy,
  };
  updateUserMarker(location);
  try {
    const result = await api(`/api/navigation/${state.route.routeId}/location`, {
      method: "POST",
      body: JSON.stringify(location),
    });
    if (result.completed) {
      elements.nextGuidance.textContent = "목적지에 도착했습니다.";
      stopNavigation();
    } else {
      const next = result.nextInstruction;
      const routeState = result.offRoute ? "경로 이탈 감지 · " : "";
      elements.nextGuidance.textContent = `${routeState}${Math.round(
        next.distanceMeters,
      )}m 후 ${next.guidance}`;
    }
    appendHapticCommands(result.commands);
  } catch (error) {
    elements.nextGuidance.textContent = error.message;
  }
}

function updateUserMarker(location) {
  const position = new window.kakao.maps.LatLng(location.latitude, location.longitude);
  if (!state.userMarker) {
    state.userMarker = new window.kakao.maps.Marker({
      map: state.map,
      position,
      zIndex: 10,
    });
  } else {
    state.userMarker.setPosition(position);
  }
}

function appendHapticCommands(commands) {
  if (!commands || !commands.length) return;
  if (!state.hapticLogStarted) {
    elements.hapticLog.replaceChildren();
    state.hapticLogStarted = true;
  }
  commands.forEach((command) => {
    const item = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = `${command.target} · ${command.pattern}`;
    item.append(code, document.createElement("br"), command.message);
    elements.hapticLog.prepend(item);
  });
}

async function sendTofReadings() {
  const value = (id) => Number(document.querySelector(`#${id}`).value);
  try {
    const result = await api("/api/tof", {
      method: "POST",
      body: JSON.stringify({
        gateway_id: "browser-simulator",
        front_left_mm: value("front-left-mm"),
        front_right_mm: value("front-right-mm"),
        left_side_mm: value("left-side-mm"),
        right_side_mm: value("right-side-mm"),
      }),
    });
    renderSensorStatus(result.sensors);
    appendHapticCommands(result.commands);
  } catch (error) {
    elements.sensorStatus.textContent = error.message;
  }
}

function renderSensorStatus(sensors) {
  elements.sensorStatus.replaceChildren();
  Object.entries(sensors).forEach(([zone, sensor]) => {
    const item = document.createElement("div");
    item.className = `sensor-chip ${sensor.level.toLowerCase()}`;
    item.textContent = `${zone}: ${sensor.distanceMm}mm · ${sensor.level}`;
    elements.sensorStatus.appendChild(item);
  });
}

// ---------------------------------------------------------------------------
// 경로 기록 모드
//
// A companion walks the real route once and taps a button at each turn,
// crosswalk, stairs, or the destination. Every tap sends the phone's current
// GPS fix plus the point type to the server; "경로 저장" writes the tagged
// points to route_N.json. This mode uses the browser's own GPS as a stand-in
// for the belt's GPS module until that integration exists.
// ---------------------------------------------------------------------------

function startRecording() {
  const name = elements.recordName.value.trim();
  if (!name) {
    elements.recordMessage.textContent = "경로 이름을 입력하세요.";
    return;
  }
  if (!navigator.geolocation) {
    elements.recordMessage.textContent = "이 브라우저에서는 위치 기능을 사용할 수 없습니다.";
    return;
  }

  elements.recordStart.disabled = true;
  elements.recordMessage.textContent = "현재 위치를 확인하는 중…";

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const coordinate = {
        longitude: position.coords.longitude,
        latitude: position.coords.latitude,
      };
      try {
        const session = await api("/api/recordings", {
          method: "POST",
          body: JSON.stringify({ name, coordinate }),
        });
        beginRecordingSession(session, coordinate);
      } catch (error) {
        elements.recordMessage.textContent = error.message;
        elements.recordStart.disabled = false;
      }
    },
    (error) => {
      elements.recordMessage.textContent = `위치 오류: ${error.message}`;
      elements.recordStart.disabled = false;
    },
    { enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 },
  );
}

function beginRecordingSession(session, startCoordinate) {
  state.recording = session;
  state.recordingLastPosition = startCoordinate;
  state.recordingPath = [startCoordinate];
  state.recordingMarkers.forEach((marker) => marker.setMap(null));
  state.recordingMarkers = [];
  if (state.recordingLine) state.recordingLine.setMap(null);
  state.recordingLine = null;

  elements.recordSetup.hidden = true;
  elements.recordActive.hidden = false;
  elements.recordBadge.hidden = false;
  elements.recordSave.disabled = true;
  elements.recordMessage.textContent = "";
  renderRecordingWaypoints(session.waypoints);
  placeRecordingMarker(session.waypoints[0]);

  state.recordingWatchId = navigator.geolocation.watchPosition(
    (position) => {
      state.recordingLastPosition = {
        longitude: position.coords.longitude,
        latitude: position.coords.latitude,
      };
      state.recordingPath.push(state.recordingLastPosition);
      updateRecordingLine();
      elements.recordGpsStatus.textContent = `GPS 정확도 ±${Math.round(
        position.coords.accuracy,
      )}m`;
    },
    (error) => {
      elements.recordGpsStatus.textContent = `위치 오류: ${error.message}`;
    },
    { enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 },
  );
}

async function tagRecordingWaypoint(type) {
  if (!state.recording || !state.recordingLastPosition) {
    elements.recordMessage.textContent = "먼저 기록을 시작하고 GPS 신호를 기다려 주세요.";
    return;
  }
  try {
    const waypoint = await api(`/api/recordings/${state.recording.recordingId}/waypoints`, {
      method: "POST",
      body: JSON.stringify({ type, coordinate: state.recordingLastPosition }),
    });
    state.recording.waypoints.push(waypoint);
    renderRecordingWaypoints(state.recording.waypoints);
    placeRecordingMarker(waypoint);
    elements.recordMessage.textContent = "";
    if (type === "destination") {
      elements.recordSave.disabled = false;
    }
  } catch (error) {
    elements.recordMessage.textContent = error.message;
  }
}

function placeRecordingMarker(waypoint) {
  if (!state.map) return;
  const position = new window.kakao.maps.LatLng(waypoint.lat, waypoint.lon);
  const marker = new window.kakao.maps.Marker({ map: state.map, position });
  const label = new window.kakao.maps.CustomOverlay({
    map: state.map,
    position,
    yAnchor: 2.1,
    content: `<div class="record-marker-label">${RECORD_TAG_LABELS[waypoint.type] || waypoint.type}</div>`,
  });
  state.recordingMarkers.push(marker, label);
  state.map.panTo(position);
}

function updateRecordingLine() {
  if (!state.map || state.recordingPath.length < 2) return;
  const path = state.recordingPath.map(
    (point) => new window.kakao.maps.LatLng(point.latitude, point.longitude),
  );
  if (state.recordingLine) {
    state.recordingLine.setPath(path);
    return;
  }
  state.recordingLine = new window.kakao.maps.Polyline({
    map: state.map,
    path,
    strokeWeight: 5,
    strokeColor: "#ffd449",
    strokeOpacity: 0.85,
    strokeStyle: "shortdash",
  });
}

function renderRecordingWaypoints(waypoints) {
  elements.recordCount.textContent = String(
    waypoints.filter((waypoint) => waypoint.type !== "start").length,
  );
  elements.recordPoints.replaceChildren();
  if (waypoints.length === 0) {
    const empty = document.createElement("li");
    empty.className = "record-empty";
    empty.textContent = "아직 태깅한 지점이 없습니다.";
    elements.recordPoints.appendChild(empty);
    return;
  }
  waypoints.forEach((waypoint) => {
    const item = document.createElement("li");
    const label = RECORD_TAG_LABELS[waypoint.type] || waypoint.type;
    const time = waypoint.recordedAt ? new Date(waypoint.recordedAt) : null;
    const timeText = time ? time.toLocaleTimeString("ko-KR", { hour12: false }) : "";
    item.innerHTML = `<strong>${label}</strong><span>${waypoint.lat.toFixed(5)}, ${waypoint.lon.toFixed(5)} · ${timeText}</span>`;
    elements.recordPoints.appendChild(item);
  });
}

async function finishRecording() {
  if (!state.recording) return;
  elements.recordSave.disabled = true;
  try {
    const result = await api(`/api/recordings/${state.recording.recordingId}/finish`, {
      method: "POST",
    });
    elements.recordMessage.textContent = `저장 완료: ${result.fileName} (지점 ${result.waypoints.length}개)`;
    elements.recordBadge.hidden = true;
    if (state.recordingWatchId !== null) {
      navigator.geolocation.clearWatch(state.recordingWatchId);
      state.recordingWatchId = null;
    }
    state.recording = null;
    elements.recordActive.hidden = true;
    elements.recordSetup.hidden = false;
    elements.recordStart.disabled = false;
    elements.recordName.value = "";
  } catch (error) {
    elements.recordMessage.textContent = error.message;
    elements.recordSave.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// 경로 안내 모드 (기록한 경로)
//
// Loads a route saved by 경로 기록 모드 and, as the browser's GPS updates,
// asks the server how far the next tagged waypoint is. The server also
// publishes haptic commands into the same buffer /api/haptics polls, and
// they show up in the existing "진동 명령 로그" panel via appendHapticCommands.
// ---------------------------------------------------------------------------

async function loadSavedRoutes() {
  elements.guidedSelect.disabled = true;
  elements.guidedStart.disabled = true;
  try {
    const { routes } = await api("/api/recordings");
    elements.guidedSelect.replaceChildren();
    if (!routes.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "저장된 경로가 없습니다";
      elements.guidedSelect.appendChild(option);
      return;
    }
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "경로를 선택하세요";
    elements.guidedSelect.appendChild(placeholder);
    routes.forEach((route) => {
      const option = document.createElement("option");
      option.value = String(route.routeId);
      option.textContent = `${route.name} (지점 ${route.waypointCount}개)`;
      elements.guidedSelect.appendChild(option);
    });
  } catch (error) {
    elements.guidedNext.textContent = error.message;
  } finally {
    elements.guidedSelect.disabled = false;
  }
}

async function startGuidedNavigation() {
  const routeId = elements.guidedSelect.value;
  if (!routeId || !navigator.geolocation) {
    elements.guidedNext.textContent = "이 브라우저에서는 위치 기능을 사용할 수 없습니다.";
    return;
  }
  elements.guidedStart.disabled = true;
  try {
    const session = await api(`/api/recorded-routes/${routeId}/start`, { method: "POST" });
    state.guided = session;
    drawGuidedRoute(session.waypoints);
    elements.guidedNext.textContent = `${session.name} 안내를 시작합니다. GPS 신호를 기다리는 중…`;
    elements.guidedStop.disabled = false;
    elements.guidedSelect.disabled = true;

    state.guidedWatchId = navigator.geolocation.watchPosition(
      updateGuidedLocation,
      (error) => {
        elements.guidedNext.textContent = `위치 오류: ${error.message}`;
      },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 },
    );
  } catch (error) {
    elements.guidedNext.textContent = error.message;
    elements.guidedStart.disabled = false;
  }
}

function stopGuidedNavigation() {
  if (state.guidedWatchId !== null) navigator.geolocation.clearWatch(state.guidedWatchId);
  state.guidedWatchId = null;
  state.guided = null;
  elements.guidedStart.disabled = !elements.guidedSelect.value;
  elements.guidedStop.disabled = true;
  elements.guidedSelect.disabled = false;
}

async function updateGuidedLocation(position) {
  if (!state.guided) return;
  const location = {
    longitude: position.coords.longitude,
    latitude: position.coords.latitude,
    accuracy_meters: position.coords.accuracy,
  };
  try {
    const result = await api(`/api/recorded-routes/${state.guided.routeId}/location`, {
      method: "POST",
      body: JSON.stringify(location),
    });
    if (result.completed) {
      elements.guidedNext.textContent = "목적지에 도착했습니다.";
      stopGuidedNavigation();
    } else {
      const next = result.nextWaypoint;
      const routeState = result.offRoute ? "경로 이탈 감지 · " : "";
      elements.guidedNext.textContent = `${routeState}${Math.round(next.distanceMeters)}m 후 ${next.label}`;
    }
    appendHapticCommands(result.commands);
  } catch (error) {
    elements.guidedNext.textContent = error.message;
  }
}

function drawGuidedRoute(waypoints) {
  if (!state.map) return;
  state.guidedMarkers.forEach((marker) => marker.setMap(null));
  state.guidedMarkers = [];
  if (state.guidedLine) state.guidedLine.setMap(null);

  const path = waypoints.map((point) => new window.kakao.maps.LatLng(point.lat, point.lon));
  state.guidedLine = new window.kakao.maps.Polyline({
    map: state.map,
    path,
    strokeWeight: 5,
    strokeColor: "#4ce5dc",
    strokeOpacity: 0.9,
    strokeStyle: "solid",
  });

  waypoints.forEach((point) => {
    const position = new window.kakao.maps.LatLng(point.lat, point.lon);
    const marker = new window.kakao.maps.Marker({ map: state.map, position });
    const label = new window.kakao.maps.CustomOverlay({
      map: state.map,
      position,
      yAnchor: 2.1,
      content: `<div class="record-marker-label">${RECORD_TAG_LABELS[point.type] || point.type}</div>`,
    });
    state.guidedMarkers.push(marker, label);
  });

  const bounds = new window.kakao.maps.LatLngBounds();
  path.forEach((point) => bounds.extend(point));
  state.map.setBounds(bounds, 70, 70, 70, 70);
}

window.addEventListener("beforeunload", () => {
  stopNavigation();
  stopGuidedNavigation();
  if (state.recordingWatchId !== null) navigator.geolocation.clearWatch(state.recordingWatchId);
});
initialize();
