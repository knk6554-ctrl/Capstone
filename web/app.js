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
};

const elements = {
  systemStatus: document.querySelector("#system-status"),
  useCurrentLocation: document.querySelector("#use-current-location"),
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
  emergencyBanner: document.querySelector("#emergency-banner"),
  emergencyMessage: document.querySelector("#emergency-message"),
  emergencyTime: document.querySelector("#emergency-time"),
  emergencyAck: document.querySelector("#emergency-ack"),
  emergencyTrigger: document.querySelector("#emergency-trigger"),
};

function switchTab(tabName) {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `tab-${tabName}`);
  });
}

function setStatus(message, isError = false) {
  elements.systemStatus.textContent = message;
  elements.systemStatus.style.color = isError ? "var(--danger)" : "var(--amber-deep)";
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
  // 버튼 이벤트는 지도 로딩 성공 여부와 무관하게 항상 연결한다.
  // (지도 SDK가 실패해도 현위치·검색·경로 생성은 좌표 기반으로 동작해야 한다.)
  bindEvents();
  try {
    const config = await api("/api/config");
    await loadKakaoMap(config.kakaoJavascriptKey);
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
  elements.useCurrentLocation.addEventListener("click", useCurrentLocation);
  elements.createRoute.addEventListener("click", createRoute);
  elements.startNavigation.addEventListener("click", startNavigation);
  elements.stopNavigation.addEventListener("click", stopNavigation);
  document.querySelector("#send-tof").addEventListener("click", sendTofReadings);

  elements.emergencyTrigger.addEventListener("click", triggerEmergency);
  elements.emergencyAck.addEventListener("click", acknowledgeEmergency);
  pollEmergency();
  setInterval(pollEmergency, 4000);
}

function locationErrorMessage(error) {
  if (!window.isSecureContext) {
    return "휴대폰 현위치는 HTTPS 주소에서만 사용할 수 있습니다. VS Code에서 8000번 포트를 전달한 HTTPS 주소로 접속하세요.";
  }
  if (error?.code === 1) {
    return "위치 권한이 거부되었습니다. 휴대폰 브라우저의 사이트 설정에서 위치 권한을 허용하세요.";
  }
  if (error?.code === 2) {
    return "현재 위치를 확인할 수 없습니다. 휴대폰 위치 서비스를 켜고 야외에서 다시 시도하세요.";
  }
  if (error?.code === 3) {
    return "GPS 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.";
  }
  return error?.message || "현재 위치를 가져오지 못했습니다.";
}

function useCurrentLocation() {
  if (!window.isSecureContext || !navigator.geolocation) {
    const message = locationErrorMessage();
    document.querySelector("#start-selected").textContent = message;
    setStatus("현위치 사용 불가", true);
    return;
  }

  const buttonLabel = elements.useCurrentLocation.innerHTML;
  elements.useCurrentLocation.disabled = true;
  elements.useCurrentLocation.textContent = "GPS 확인 중…";
  setStatus("현위치 확인 중");

  navigator.geolocation.getCurrentPosition(
    (position) => {
      const accuracy = Math.round(position.coords.accuracy);
      const currentPlace = {
        id: "current-location",
        name: "현위치",
        address: `GPS 정확도 약 ${accuracy}m`,
        roadAddress: "",
        phone: "",
        placeUrl: "",
        coordinate: {
          longitude: position.coords.longitude,
          latitude: position.coords.latitude,
        },
      };
      document.querySelector("#start-query").value = "현위치";
      selectPlace("start", currentPlace);
      updateUserMarker(currentPlace.coordinate);
      setStatus("현위치 설정 완료");
      elements.useCurrentLocation.disabled = false;
      elements.useCurrentLocation.innerHTML = buttonLabel;
    },
    (error) => {
      const message = locationErrorMessage(error);
      document.querySelector("#start-selected").textContent = message;
      setStatus("GPS 오류", true);
      elements.useCurrentLocation.disabled = false;
      elements.useCurrentLocation.innerHTML = buttonLabel;
    },
    { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 },
  );
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

  // 지도가 아직 준비되지 않았어도 출발/도착 선택 자체는 유지되어야 한다.
  if (state.map && window.kakao?.maps) {
    state.map.panTo(
      new window.kakao.maps.LatLng(
        place.coordinate.latitude,
        place.coordinate.longitude,
      ),
    );
  }
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
  // 지도 SDK가 없으면 경로 요약/안내 텍스트만 표시하고 지도 그리기는 건너뛴다.
  if (!state.map || !window.kakao?.maps) return;
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
    strokeColor: "#0f6e56",
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
  if (!state.route) return;
  if (!window.isSecureContext || !navigator.geolocation) {
    elements.nextGuidance.textContent = locationErrorMessage();
    setStatus("현위치 사용 불가", true);
    return;
  }
  state.watchId = navigator.geolocation.watchPosition(
    updateLocation,
    (error) => {
      elements.nextGuidance.textContent = locationErrorMessage(error);
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
  if (!state.map || !window.kakao?.maps) return;
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
// 위험 버튼 알림
//
// The danger-button press (simulated here) sets one active alert on the
// server. This page polls it every few seconds and shows a banner while
// unacknowledged. The caregiver must have this page open -- there is no
// background push yet.
// ---------------------------------------------------------------------------

let lastSeenAlertId = null;

async function triggerEmergency() {
  elements.emergencyTrigger.disabled = true;
  const payload = { message: "도움이 필요합니다." };
  try {
    if (navigator.geolocation) {
      const position = await new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
          resolve,
          () => resolve(null),
          { enableHighAccuracy: true, timeout: 4000 },
        );
      });
      if (position) {
        payload.coordinate = {
          longitude: position.coords.longitude,
          latitude: position.coords.latitude,
        };
      }
    }
    await api("/api/emergency", { method: "POST", body: JSON.stringify(payload) });
    await pollEmergency();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    elements.emergencyTrigger.disabled = false;
  }
}

async function pollEmergency() {
  try {
    const { alert } = await api("/api/emergency");
    if (alert) {
      showEmergencyBanner(alert);
    } else {
      hideEmergencyBanner();
    }
  } catch (error) {
    // Polling failures shouldn't interrupt the rest of the page.
  }
}

function showEmergencyBanner(alert) {
  lastSeenAlertId = alert.alertId;
  elements.emergencyBanner.hidden = false;
  elements.emergencyMessage.textContent = alert.message;
  const time = new Date(alert.triggeredAt);
  elements.emergencyTime.textContent = time.toLocaleTimeString("ko-KR", { hour12: false });
  elements.emergencyAck.dataset.alertId = alert.alertId;
}

function hideEmergencyBanner() {
  elements.emergencyBanner.hidden = true;
  lastSeenAlertId = null;
}

async function acknowledgeEmergency() {
  const alertId = elements.emergencyAck.dataset.alertId || lastSeenAlertId;
  if (!alertId) return;
  elements.emergencyAck.disabled = true;
  try {
    await api(`/api/emergency/${alertId}/acknowledge`, { method: "POST" });
    hideEmergencyBanner();
  } catch (error) {
    hideEmergencyBanner();
  } finally {
    elements.emergencyAck.disabled = false;
  }
}

window.addEventListener("beforeunload", stopNavigation);
initialize();
