"use strict";

const state = {
  map: null,
  routeLine: null,
  markers: [],
  userMarker: null,
  stepMarker: null,
  stepMarkerEnd: null,
  hazardLines: [],
  stepHighlightLine: null,
  selected: { start: null, destination: null },
  route: null,
  watchId: null,
  hapticLogStarted: false,
  gpsFixCount: 0,
  accuracyCircle: null,
  // "전체 경로" / "현재 이동 경로" 지도 보기 모드 — GPS 안내 중에만 의미가 있다.
  routeViewMode: "full",
  lastAutoStepIndex: -1,
  lastKnownStepIndex: null,
  // 시연 모드: 실제 GPS 대신 안내 목록 클릭으로 각 지점 도달을 흉내낸다.
  demoMode: false,
};

// 위험 구간(계단·횡단보도)을 지도에 상시 표시할 색 — 성격이 다른 위험이라 색을 구분한다.
const HAZARD_LINE_COLORS = {
  STAIRS: "#d9730d",
  CROSSWALK: "#c1352b",
};
// 안내 단계를 클릭했을 때 그 구간만 덧그리는 강조색.
const STEP_HIGHLIGHT_COLOR = "#2f6f5e";

const elements = {
  systemStatus: document.querySelector("#system-status"),
  useCurrentLocation: document.querySelector("#use-current-location"),
  startQuery: document.querySelector("#start-query"),
  startSearchButton: document.querySelector('[data-search="start"]'),
  createRoute: document.querySelector("#create-route"),
  routeMode: document.querySelector("#route-mode"),
  routeMessage: document.querySelector("#route-message"),
  routeSafetyWarning: document.querySelector("#route-safety-warning"),
  routeHazards: document.querySelector("#route-hazards"),
  routeComparison: document.querySelector("#route-comparison"),
  routeSummary: document.querySelector("#route-summary"),
  summaryDistance: document.querySelector("#summary-distance"),
  summaryTime: document.querySelector("#summary-time"),
  summarySteps: document.querySelector("#summary-steps"),
  mapCaption: document.querySelector("#map-caption"),
  directions: document.querySelector("#directions"),
  startNavigation: document.querySelector("#start-navigation"),
  stopNavigation: document.querySelector("#stop-navigation"),
  nextGuidance: document.querySelector("#next-guidance"),
  nextGuidanceText: document.querySelector("#next-guidance-text"),
  gpsDebug: document.querySelector("#gps-debug"),
  gpsCoord: document.querySelector("#gps-coord"),
  gpsAccuracy: document.querySelector("#gps-accuracy"),
  gpsAge: document.querySelector("#gps-age"),
  gpsOffRoute: document.querySelector("#gps-offroute"),
  gpsCount: document.querySelector("#gps-count"),
  hapticLog: document.querySelector("#haptic-log"),
  sensorStatus: document.querySelector("#sensor-status"),
  emergencyBanner: document.querySelector("#emergency-banner"),
  emergencyMessage: document.querySelector("#emergency-message"),
  emergencyTime: document.querySelector("#emergency-time"),
  emergencyAck: document.querySelector("#emergency-ack"),
  panelToggle: document.querySelector("#panel-toggle"),
  recenterButton: document.querySelector("#recenter-location"),
  etaBar: document.querySelector("#eta-bar"),
  etaTime: document.querySelector("#eta-time"),
  etaDistance: document.querySelector("#eta-distance"),
  etaArrival: document.querySelector("#eta-arrival"),
  routeViewToggle: document.querySelector("#route-view-toggle"),
  demoModeCheckbox: document.querySelector("#demo-mode-checkbox"),
  resetProgressButton: document.querySelector("#reset-progress"),
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

// 다음 안내 문구 갱신. active를 넘기면 "대기/안내 준비" 조용한 톤 ↔ "실제 안내 중" 굵은
// 배너 톤을 전환하고, 넘기지 않으면(에러 메시지 등) 지금 톤을 그대로 유지한다.
function setGuidance(text, active) {
  elements.nextGuidanceText.textContent = text;
  if (active !== undefined) {
    elements.nextGuidance.classList.toggle("is-active", active);
  }
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
        locateAndCenterMap({ silent: true });
      });
    };
    script.onerror = () => reject(new Error("카카오 지도 SDK를 불러오지 못했습니다."));
    document.head.appendChild(script);
  });
}

// 지도를 현재 위치로 이동 + 파란 점 표시. silent=true면 실패해도 아무 표시 없이 조용히
// 넘어간다(최초 지도 로딩 시 사용). 버튼 클릭 등 사용자가 직접 요청했을 때는 실패 이유를
// system-status에 알려준다.
function locateAndCenterMap({ silent = false } = {}) {
  if (!window.isSecureContext || !navigator.geolocation || !state.map) {
    if (!silent) setStatus(locationErrorMessage(), true);
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      const location = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy_meters: position.coords.accuracy,
      };
      state.map.setCenter(
        new window.kakao.maps.LatLng(location.latitude, location.longitude),
      );
      updateUserMarker(location);
      if (!silent) setStatus("현재 위치로 이동했습니다.");
    },
    (error) => {
      if (!silent) setStatus(locationErrorMessage(error), true);
    },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
  );
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

  elements.emergencyAck.addEventListener("click", acknowledgeEmergency);
  bindHelpHints();
  bindPanelToggle();
  bindRouteViewToggle();
  elements.recenterButton.addEventListener("click", () => locateAndCenterMap());
  elements.demoModeCheckbox.addEventListener("change", (event) => {
    setDemoMode(event.target.checked);
  });
  elements.resetProgressButton.addEventListener("click", resetNavigationProgress);
  pollEmergency();
  setInterval(pollEmergency, 4000);

  // 지도가 전체 화면을 차지하므로, 창 크기가 바뀌면(모바일 회전 포함) 카카오맵도 다시 그려야 한다.
  window.addEventListener("resize", () => {
    if (state.map) state.map.relayout();
    // 데스크톱 폭으로 넘어가면 모바일 시트에서 남은 인라인 높이를 지워 CSS(좌측 고정 칼럼)를 되찾는다.
    if (!isMobilePanelLayout()) {
      const panel = elements.panelToggle?.closest(".panel");
      if (panel) panel.style.height = "";
    }
    syncMapOverlayPositions();
  });
}

// 모바일 하단 시트: 손잡이를 탭하면 펼침/접힘 전환, 위아래로 끌면 원하는 높이로 조절한다.
// (데스크톱에서는 패널이 좌측 고정 칼럼이라 손잡이 자체가 CSS로 숨겨진다.)
const SHEET_PEEK_HEIGHT = 132;
const sheetExpandedHeight = () => Math.round(window.innerHeight * 0.66);
const isMobilePanelLayout = () => window.matchMedia("(max-width: 880px)").matches;

// 지도 위 오버레이(현재 위치 버튼 · ETA 바)는 하단 시트 위 가장자리에 항상 붙어
// 다닌다 — 시트가 얼마나 펼쳐져 있든(접힘/드래그 중/펼침) 그 바로 위에 위치.
// panelHeightPx를 넘기면 그 값을 그대로 쓴다 — 시트에 CSS 트랜지션이 걸려 있을 때
// getBoundingClientRect()로 다시 재는 값은 트랜지션 시작 시점(이전 높이)을 반환하기
// 때문에, 우리가 이미 알고 있는 목표 높이를 직접 넘겨줘야 정확하다.
function syncMapOverlayPositions(panelHeightPx) {
  const panel = document.querySelector(".panel");
  if (!panel) return;
  const overlays = [elements.recenterButton, elements.etaBar].filter(Boolean);
  if (!isMobilePanelLayout()) {
    overlays.forEach((el) => {
      el.style.bottom = "";
    });
    return;
  }
  const panelHeight = panelHeightPx ?? panel.getBoundingClientRect().height;
  overlays.forEach((el) => {
    el.style.bottom = `${panelHeight + 16}px`;
  });
}

function bindPanelToggle() {
  const toggle = elements.panelToggle;
  const panel = toggle?.closest(".panel");
  if (!toggle || !panel) return;

  let dragging = false;
  let dragged = false;
  let startY = 0;
  let startHeight = 0;

  const setPanelHeight = (px) => {
    const clamped = Math.min(sheetExpandedHeight(), Math.max(SHEET_PEEK_HEIGHT, px));
    panel.style.height = `${clamped}px`;
    syncMapOverlayPositions(clamped);
  };

  const setCollapsed = (collapsed) => {
    const targetHeight = collapsed ? SHEET_PEEK_HEIGHT : sheetExpandedHeight();
    panel.classList.toggle("is-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    panel.style.height = `${targetHeight}px`;
    syncMapOverlayPositions(targetHeight);
  };

  toggle.addEventListener("pointerdown", (event) => {
    if (!isMobilePanelLayout()) return;
    dragging = true;
    dragged = false;
    startY = event.clientY;
    startHeight = panel.getBoundingClientRect().height;
    panel.style.transition = "none";
    if (elements.recenterButton) elements.recenterButton.style.transition = "none";
    try {
      toggle.setPointerCapture(event.pointerId);
    } catch {
      // 일부 브라우저/포인터 종류는 캡처를 지원하지 않을 수 있다 — 드래그 자체는 계속 동작한다.
    }
  });

  toggle.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const delta = startY - event.clientY;
    if (Math.abs(delta) > 4) dragged = true;
    setPanelHeight(startHeight + delta);
  });

  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    panel.style.transition = "";
    if (elements.recenterButton) elements.recenterButton.style.transition = "";
    if (!dragged) {
      // 움직임 없이 그냥 탭한 경우 — 펼침/접힘 전환
      setCollapsed(!panel.classList.contains("is-collapsed"));
      return;
    }
    // 끌어서 놓은 경우 — 놓은 높이가 중간값보다 크면 펼침, 작으면 접힘으로 스냅
    const current = panel.getBoundingClientRect().height;
    const mid = (SHEET_PEEK_HEIGHT + sheetExpandedHeight()) / 2;
    setCollapsed(current < mid);
  };

  toggle.addEventListener("pointerup", endDrag);
  toggle.addEventListener("pointercancel", endDrag);

  syncMapOverlayPositions();
}

// 회색 안내 문구를 ? 아이콘 뒤로 접어두고, 호버(데스크톱) 또는 클릭(터치)으로 펼친다.
function bindHelpHints() {
  const hints = [...document.querySelectorAll(".help-hint")];
  const closeAll = (except) => {
    for (const hint of hints) {
      if (hint === except) continue;
      hint.classList.remove("is-open");
      hint
        .querySelector(".help-hint__trigger")
        ?.setAttribute("aria-expanded", "false");
    }
  };
  for (const hint of hints) {
    const trigger = hint.querySelector(".help-hint__trigger");
    if (!trigger) continue;
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      const open = hint.classList.toggle("is-open");
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) closeAll(hint);
    });
  }
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".help-hint")) closeAll();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAll();
  });
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

// 현위치 잠금 상태에서는 출발지 검색 UI를 잠가서, "검색 결과가 없습니다"
// 같은 혼동을 없애고 GPS 좌표가 출발지로 고정돼 있음을 분명히 보여준다.
const CURRENT_LOCATION_LABEL = "📍 현재 위치 (GPS)";

function lockStartToCurrentLocation() {
  elements.startQuery.value = CURRENT_LOCATION_LABEL;
  elements.startQuery.readOnly = true;
  elements.startQuery.classList.add("is-locked");
  if (elements.startSearchButton) elements.startSearchButton.disabled = true;
  elements.useCurrentLocation.dataset.active = "true";
  elements.useCurrentLocation.innerHTML =
    '<i class="ti ti-x" aria-hidden="true"></i> 현위치 해제';
}

function unlockStart() {
  elements.startQuery.readOnly = false;
  elements.startQuery.classList.remove("is-locked");
  elements.startQuery.value = "";
  if (elements.startSearchButton) elements.startSearchButton.disabled = false;
  delete elements.useCurrentLocation.dataset.active;
  elements.useCurrentLocation.innerHTML =
    '<i class="ti ti-current-location" aria-hidden="true"></i> 현위치';
  if (state.selected.start && state.selected.start.id === "current-location") {
    state.selected.start = null;
    const selected = document.querySelector("#start-selected");
    selected.textContent = "선택된 장소 없음";
    selected.classList.remove("is-selected");
    elements.createRoute.disabled = true;
  }
  setStatus("현위치 해제됨");
}

function useCurrentLocation() {
  // 이미 현위치가 잡혀 있으면 토글로 해제
  if (elements.useCurrentLocation.dataset.active === "true") {
    unlockStart();
    return;
  }

  if (!window.isSecureContext || !navigator.geolocation) {
    const message = locationErrorMessage();
    document.querySelector("#start-selected").textContent = message;
    setStatus("현위치 사용 불가", true);
    return;
  }

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
      selectPlace("start", currentPlace);
      lockStartToCurrentLocation();
      updateUserMarker(currentPlace.coordinate);
      setStatus("현위치 설정 완료");
      elements.useCurrentLocation.disabled = false;
    },
    (error) => {
      const message = locationErrorMessage(error);
      document.querySelector("#start-selected").textContent = message;
      setStatus("GPS 오류", true);
      elements.useCurrentLocation.disabled = false;
      elements.useCurrentLocation.innerHTML =
        '<i class="ti ti-current-location" aria-hidden="true"></i> 현위치';
    },
    { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 },
  );
}

async function searchPlaces(kind) {
  // 현위치로 고정된 출발지는 검색으로 덮어쓰지 않는다.
  if (kind === "start" && elements.startQuery.readOnly) return;

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

const ROUTE_MODE_LABELS = {
  ACCESSIBLE: "안전 경로",
  SHORTEST: "빠른 경로",
  BROAD_FIRST: "넓은 길 경로",
};

function resetRouteExtras() {
  for (const el of [
    elements.routeSafetyWarning,
    elements.routeHazards,
    elements.routeComparison,
  ]) {
    el.hidden = true;
    el.textContent = "";
  }
}

function renderHazards(route) {
  const hazards = route.hazards || { stairs: 0, crosswalks: 0 };
  const parts = [];
  if (hazards.stairs) parts.push(`계단 ${hazards.stairs}곳`);
  if (hazards.crosswalks) parts.push(`횡단보도 ${hazards.crosswalks}곳`);
  elements.routeHazards.textContent = parts.length
    ? `이 경로: ${parts.join(" · ")}`
    : "이 경로에는 계단·횡단보도 구간이 없습니다.";
  elements.routeHazards.hidden = false;

  // 안전 경로를 골랐는데도 계단이 남아 있으면 분명하게 경고한다.
  if (route.routeMode === "ACCESSIBLE" && hazards.stairs > 0) {
    elements.routeSafetyWarning.textContent =
      `⚠️ 안전 경로에도 계단 ${hazards.stairs}곳이 포함되어 있습니다. ` +
      `안내 중 진동으로 알려드립니다.`;
    elements.routeSafetyWarning.hidden = false;
  }
}

// 거리·시간 차이를 "320m 더 길고 약 3분 더 걸리는" 같은 한 구절로 만든다.
// sign > 0 이면 현재 경로가 더 길다/느리다(비용), < 0 이면 더 짧다/빠르다(이득).
function describeDelta(distDelta, minDelta) {
  const bits = [];
  if (distDelta > 0) bits.push(`${distDelta}m 더 길`);
  else if (distDelta < 0) bits.push(`${-distDelta}m 더 짧`);
  if (minDelta > 0) bits.push(distDelta > 0 ? "약 " + minDelta + "분 더 걸리" : `약 ${minDelta}분 더 느리`);
  else if (minDelta < 0) bits.push(`약 ${-minDelta}분 더 빠르`);
  if (!bits.length) return null;
  return bits.join("고 ") + "는";
}

function renderComparison(route) {
  const c = route.comparison;
  if (!c) return;
  const distDelta = Math.round(c.distanceDeltaMeters);
  const minDelta = Math.round(c.timeDeltaSeconds / 60);
  const primaryLabel = ROUTE_MODE_LABELS[route.routeMode] || route.routeMode;
  const otherLabel = c.label || ROUTE_MODE_LABELS[c.mode] || c.mode;

  // 양수 = 반대편(otherLabel) 경로가 그 위험 구간을 더 지난다
  const avoided = [];
  if (c.stairsDelta > 0) avoided.push(`계단 ${c.stairsDelta}곳`);
  if (c.crosswalksDelta > 0) avoided.push(`횡단보도 ${c.crosswalksDelta}곳`);
  const extra = [];
  if (c.stairsDelta < 0) extra.push(`계단 ${-c.stairsDelta}곳`);
  if (c.crosswalksDelta < 0) extra.push(`횡단보도 ${-c.crosswalksDelta}곳`);

  let message;
  if (route.routeMode === "ACCESSIBLE" && avoided.length) {
    const delta = describeDelta(distDelta, minDelta);
    const clause = delta
      ? `${otherLabel}보다 ${delta} 대신`
      : `${otherLabel}와 거리는 비슷하면서`;
    message = `현재 ${primaryLabel}는 ${clause} ${avoided.join("·")}을 피합니다.`;
  } else if (route.routeMode === "SHORTEST" && extra.length) {
    const delta = describeDelta(-distDelta, -minDelta);
    const clause = delta ? `${otherLabel}보다 ${delta} 대신` : "";
    message = `현재 ${primaryLabel}는 ${clause} ${extra.join(
      "·",
    )}을 더 지납니다. 안전이 우선이면 안전 경로를 선택하세요.`;
  } else {
    message = `${otherLabel}: ${c.totalDistanceMeters.toLocaleString()}m · 약 ${Math.max(
      1,
      Math.round(c.totalTimeSeconds / 60),
    )}분 · 계단 ${c.hazards.stairs}곳 · 횡단보도 ${c.hazards.crosswalks}곳`;
  }
  elements.routeComparison.textContent = message;
  elements.routeComparison.hidden = false;
}

async function createRoute() {
  elements.createRoute.disabled = true;
  resetRouteExtras();
  const modeLabel = ROUTE_MODE_LABELS[elements.routeMode.value] || "보행";
  elements.routeMessage.textContent = `${modeLabel}를 찾고 있습니다…`;
  try {
    const route = await api("/api/routes", {
      method: "POST",
      body: JSON.stringify({
        start: placeRequest(state.selected.start),
        destination: placeRequest(state.selected.destination),
        route_mode: elements.routeMode.value,
        compare: true,
      }),
    });
    state.route = route;
    drawRoute(route);
    renderRoute(route);
    renderHazards(route);
    renderComparison(route);
    elements.routeMessage.textContent = `${modeLabel}를 만들었습니다.`;
    if (state.demoMode) {
      // 시연 모드가 이미 켜져 있었다면(경로 없을 때 미리 켜둔 경우) 새 경로에 맞춰 안내 UI를 켠다.
      elements.startNavigation.disabled = true;
      enterNavigationUiState();
      setStatus("시연 모드 · 목록을 눌러 도달을 시뮬레이션합니다");
    } else {
      elements.startNavigation.disabled = false;
      setStatus("경로 준비 완료");
    }
  } catch (error) {
    elements.routeMessage.textContent = error.message;
    setStatus("경로 생성 실패", true);
  } finally {
    elements.createRoute.disabled = false;
  }
}

// 출발·도착을 서로 다른 색 핀으로, 현재 위치(파란 점)와도 확실히 구분되게.
function pinImage(fillColor) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="30" height="40" viewBox="0 0 30 40">` +
    `<path d="M15 1C7.3 1 1 7.3 1 15c0 10 14 24 14 24s14-14 14-24C29 7.3 22.7 1 15 1z" ` +
    `fill="${fillColor}" stroke="#ffffff" stroke-width="2"/>` +
    `<circle cx="15" cy="15" r="5" fill="#ffffff"/></svg>`;
  return new window.kakao.maps.MarkerImage(
    "data:image/svg+xml," + encodeURIComponent(svg),
    new window.kakao.maps.Size(30, 40),
    { offset: new window.kakao.maps.Point(15, 40) },
  );
}

function drawRoute(route) {
  // 지도 SDK가 없으면 경로 요약/안내 텍스트만 표시하고 지도 그리기는 건너뛴다.
  if (!state.map || !window.kakao?.maps) return;
  if (state.routeLine) state.routeLine.setMap(null);
  state.markers.forEach((marker) => marker.setMap(null));
  state.markers = [];
  if (state.accuracyCircle) {
    state.accuracyCircle.setMap(null);
    state.accuracyCircle = null;
  }
  if (state.stepMarker) {
    state.stepMarker.setMap(null);
    state.stepMarker = null;
  }
  if (state.stepMarkerEnd) {
    state.stepMarkerEnd.setMap(null);
    state.stepMarkerEnd = null;
  }
  if (state.stepHighlightLine) {
    state.stepHighlightLine.setMap(null);
    state.stepHighlightLine = null;
  }
  state.hazardLines.forEach((line) => line.setMap(null));
  state.hazardLines = [];

  const path = route.path.map(
    (point) => new window.kakao.maps.LatLng(point.latitude, point.longitude),
  );
  state.routeLine = new window.kakao.maps.Polyline({
    map: state.map,
    path,
    strokeWeight: 7,
    strokeColor: "#17303d",
    strokeOpacity: 0.95,
    strokeStyle: "solid",
  });

  // 계단·횡단보도 구간은 클릭 전부터 위험색으로 상시 표시 — 기본 경로선 위에 덧그린다.
  route.steps.forEach((step) => {
    const hazardColor = HAZARD_LINE_COLORS[step.maneuver];
    if (!hazardColor || !step.path || step.path.length < 2) return;
    state.hazardLines.push(
      new window.kakao.maps.Polyline({
        map: state.map,
        path: step.path.map(
          (point) => new window.kakao.maps.LatLng(point.latitude, point.longitude),
        ),
        strokeWeight: 7,
        strokeColor: hazardColor,
        strokeOpacity: 1,
        strokeStyle: "solid",
      }),
    );
  });

  [
    { place: route.start, color: "#2f6f5e", title: "출발" },
    { place: route.destination, color: "#17303d", title: "도착" },
  ].forEach(({ place, color, title }) => {
    state.markers.push(
      new window.kakao.maps.Marker({
        map: state.map,
        title,
        image: pinImage(color),
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

function formatRemainingDistance(meters) {
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)}km`;
  return `${Math.round(meters)}m`;
}

// GPS 안내 중 지도 하단 중앙에 뜨는 ETA 바 — 지도앱들이 흔히 쓰는 위치·구성
// (남은 시간 · 남은 거리 · 도착 예정 시각)을 그대로 따른다.
function updateEtaBar(result) {
  if (!elements.etaBar) return;
  if (!result || result.completed) {
    elements.etaBar.hidden = true;
    return;
  }
  const remainingSeconds = Math.max(0, result.remainingTimeSeconds ?? 0);
  const arrival = new Date(Date.now() + remainingSeconds * 1000);
  elements.etaTime.textContent = formatDuration(remainingSeconds);
  elements.etaDistance.textContent = formatRemainingDistance(result.remainingDistanceMeters ?? 0);
  elements.etaArrival.textContent = `${arrival.toLocaleTimeString("ko-KR", {
    hour: "numeric",
    minute: "2-digit",
  })} 도착`;
  elements.etaBar.hidden = false;
}

const MANEUVER_LABELS = {
  START: "출발",
  STRAIGHT: "직진",
  LEFT: "좌회전",
  RIGHT: "우회전",
  UTURN: "유턴",
  CROSSWALK: "🚸 횡단보도",
  STAIRS: "⚠️ 계단",
  ARRIVE: "도착",
  OTHER: "이동",
};

function renderRoute(route) {
  elements.routeSummary.hidden = false;
  elements.summaryDistance.textContent = `${route.totalDistanceMeters.toLocaleString()} m`;
  elements.summaryTime.textContent = formatDuration(route.totalTimeSeconds);
  elements.summarySteps.textContent = `${route.steps.length}개`;
  elements.mapCaption.textContent = `${route.start.name} → ${route.destination.name}`;
  elements.directions.replaceChildren();
  route.steps.forEach((step, index) => {
    const item = document.createElement("li");
    if (step.maneuver === "STAIRS") item.className = "is-stairs";
    else if (step.maneuver === "CROSSWALK") item.className = "is-crosswalk";
    const maneuver = document.createElement("strong");
    maneuver.textContent = `[${MANEUVER_LABELS[step.maneuver] || step.maneuver}] `;
    item.append(maneuver, step.guidance || `${step.distanceMeters}m 이동`);

    // 클릭(또는 키보드 포커스 + Enter/Space)하면 지도가 해당 단계 위치로 이동하고
    // 단계 번호가 적힌 마커가 그 위치에만 나타난다.
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-label", `${index + 1}번째 안내 단계를 지도에서 보기`);
    const activateStep = () => {
      // 시연 모드: 실제로 걷지 않아도 이 지점에 방금 도달한 것처럼 서버에 위치를
      // 전달한다 — 실제 GPS 수신과 똑같은 경로를 타므로 진동도 실제로 울린다.
      if (state.demoMode) {
        simulateStepArrival(index);
      } else {
        focusRouteStep(route, index, item);
      }
    };
    item.addEventListener("click", activateStep);
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      activateStep();
    });

    elements.directions.appendChild(item);
  });
  setGuidance("GPS 안내를 시작하면 다음 회전까지 거리를 표시합니다.", false);
  elements.gpsDebug.hidden = true;
  state.gpsFixCount = 0;
}

// 안내 단계 클릭 시: 지도를 해당 좌표로 pan, 그 구간만 강조색 선으로 덧그리고
// 번호 마커를 띄운다. 나머지 경로선은 흐리게 처리해 선택 구간을 도드라지게 한다.
function focusRouteStep(route, index, item, { auto = false } = {}) {
  const step = route.steps?.[index];
  if (!step?.location || !state.map || !window.kakao?.maps) return;
  // "현재 이동 경로" 모드일 땐 실시간 위치가 강조를 넘겨받으므로 사람이 직접 누르는
  // 클릭은 무시한다(auto=true인 자동 호출만 통과).
  if (!auto && state.routeViewMode === "live") return;

  elements.directions
    .querySelectorAll("li.is-active-step")
    .forEach((li) => li.classList.remove("is-active-step"));
  item.classList.add("is-active-step");

  const position = new window.kakao.maps.LatLng(
    step.location.latitude,
    step.location.longitude,
  );
  state.map.panTo(position);

  // 선택 구간을 도드라지게: 기본 경로선 + 위험 구간선을 흐리게 낮춘다.
  // (새 경로를 만들면 drawRoute가 선을 새로 그리므로 자연히 원래 밝기로 돌아온다.)
  if (state.routeLine) state.routeLine.setOptions({ strokeOpacity: 0.25 });
  state.hazardLines.forEach((line) => line.setOptions({ strokeOpacity: 0.3 }));

  if (state.stepMarker) {
    state.stepMarker.setMap(null);
    state.stepMarker = null;
  }
  if (state.stepMarkerEnd) {
    state.stepMarkerEnd.setMap(null);
    state.stepMarkerEnd = null;
  }
  if (state.stepHighlightLine) {
    state.stepHighlightLine.setMap(null);
    state.stepHighlightLine = null;
  }

  if (step.path?.length >= 2) {
    state.stepHighlightLine = new window.kakao.maps.Polyline({
      map: state.map,
      path: step.path.map(
        (point) => new window.kakao.maps.LatLng(point.latitude, point.longitude),
      ),
      strokeWeight: 9,
      strokeColor: STEP_HIGHLIGHT_COLOR,
      strokeOpacity: 1,
      strokeStyle: "solid",
      zIndex: 20,
    });
  }

  // 매번 새 오버레이(=새 DOM 노드)를 만들어야 팝 애니메이션이 다시 재생된다.
  state.stepMarker = new window.kakao.maps.CustomOverlay({
    map: state.map,
    position,
    content: `<div class="map-step-marker">${index + 1}</div>`,
    xAnchor: 0.5,
    yAnchor: 0.5,
    zIndex: 30,
  });

  // 구간이 허공에서 끊긴 것처럼 보이지 않도록, 다음 단계가 있으면 그 끝점에도
  // (옅은 톤의) 다음 번호 마커를 함께 띄운다 — 마지막 단계는 도착 핀이 이미 있어 생략.
  const hasNextStep = index < route.steps.length - 1;
  if (hasNextStep && step.path?.length >= 2) {
    const endPoint = step.path[step.path.length - 1];
    state.stepMarkerEnd = new window.kakao.maps.CustomOverlay({
      map: state.map,
      position: new window.kakao.maps.LatLng(endPoint.latitude, endPoint.longitude),
      content: `<div class="map-step-marker map-step-marker--secondary">${index + 2}</div>`,
      xAnchor: 0.5,
      yAnchor: 0.5,
      zIndex: 29,
    });
  }
}

// focusRouteStep()이 켠 강조(마커·강조선·흐림)를 전부 되돌려 평범한 전체 경로 모습으로.
function clearStepFocus() {
  elements.directions
    .querySelectorAll("li.is-active-step")
    .forEach((li) => li.classList.remove("is-active-step"));
  if (state.routeLine) state.routeLine.setOptions({ strokeOpacity: 0.95 });
  state.hazardLines.forEach((line) => line.setOptions({ strokeOpacity: 1 }));
  if (state.stepMarker) {
    state.stepMarker.setMap(null);
    state.stepMarker = null;
  }
  if (state.stepMarkerEnd) {
    state.stepMarkerEnd.setMap(null);
    state.stepMarkerEnd = null;
  }
  if (state.stepHighlightLine) {
    state.stepHighlightLine.setMap(null);
    state.stepHighlightLine = null;
  }
}

// GPS 안내 중에만 뜨는 "전체 경로 / 현재 이동 경로" 전환. 기본값은 "현재 이동 경로" —
// 안내를 시작한 목적 자체가 지금 어디를 걷고 있는지 보려는 것이라 자동 추적을 우선한다.
function setRouteViewMode(mode) {
  state.routeViewMode = mode;
  document.querySelectorAll(".route-view-toggle__btn").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.viewMode === mode);
  });
  elements.directions.classList.toggle("is-auto-following", mode === "live");

  if (mode === "full") {
    clearStepFocus();
    return;
  }
  // "현재 이동 경로"로 (다시) 전환: 마지막으로 알고 있던 현재 단계를 즉시 반영한다.
  state.lastAutoStepIndex = -1;
  if (state.lastKnownStepIndex != null) {
    applyAutoStepFocus(state.lastKnownStepIndex);
  }
}

function applyAutoStepFocus(stepIndex) {
  state.lastKnownStepIndex = stepIndex;
  if (state.routeViewMode !== "live") return;
  if (stepIndex === state.lastAutoStepIndex) return;
  const item = elements.directions.querySelectorAll("li")[stepIndex];
  if (!item || !state.route) return;
  state.lastAutoStepIndex = stepIndex;
  focusRouteStep(state.route, stepIndex, item, { auto: true });
}

function bindRouteViewToggle() {
  document.querySelectorAll(".route-view-toggle__btn").forEach((button) => {
    button.addEventListener("click", () => setRouteViewMode(button.dataset.viewMode));
  });
}

// 실제 GPS든 시연 모드든 "안내 중" 화면 상태는 동일 — 여기서 한 번만 켠다.
function enterNavigationUiState() {
  state.gpsFixCount = 0;
  elements.gpsCount.textContent = "0";
  elements.gpsDebug.hidden = false;
  // 안내를 시작할 때만 지도 보기 모드 전환이 뜬다 — 기본은 "현재 이동 경로"(실시간 추적).
  state.lastAutoStepIndex = -1;
  state.lastKnownStepIndex = null;
  elements.routeViewToggle.hidden = false;
  setRouteViewMode("live");
  pushRouteViewToggleBelowBanner();
}

function startNavigation() {
  if (!state.route) return;
  if (!window.isSecureContext || !navigator.geolocation) {
    setGuidance(locationErrorMessage());
    setStatus("현위치 사용 불가", true);
    return;
  }
  enterNavigationUiState();
  state.watchId = navigator.geolocation.watchPosition(
    updateLocation,
    (error) => {
      setGuidance(locationErrorMessage(error));
      elements.gpsOffRoute.textContent = `신호 오류 (${error.code})`;
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
  if (state.accuracyCircle) {
    state.accuracyCircle.setMap(null);
    state.accuracyCircle = null;
  }
  elements.startNavigation.disabled = !state.route;
  elements.stopNavigation.disabled = true;
  setStatus("GPS 안내 중지");
  if (elements.etaBar) elements.etaBar.hidden = true;
  elements.routeViewToggle.hidden = true;
  setRouteViewMode("full");
}

// 시연 모드: 실제로 걷지 않고도 안내 목록을 눌러 각 지점 도달을 흉내낸다.
// 실제 GPS와 동시에 돌면 위치가 뒤섞이니 서로 배타적으로 둔다.
function setDemoMode(enabled) {
  state.demoMode = enabled;
  elements.directions.classList.toggle("is-demo-mode", enabled);

  if (enabled) {
    if (state.watchId !== null) stopNavigation();
    elements.startNavigation.disabled = true;
    if (state.route) {
      enterNavigationUiState();
      setStatus("시연 모드 · 목록을 눌러 도달을 시뮬레이션합니다");
    }
    return;
  }

  elements.startNavigation.disabled = !state.route;
  elements.etaBar.hidden = true;
  elements.routeViewToggle.hidden = true;
  elements.gpsDebug.hidden = true;
  setRouteViewMode("full");
  setStatus(state.route ? "경로 준비 완료" : "시스템 준비 완료");
}

// 안내 목록 번호를 누르면 그 지점에 실제로 도달한 것처럼 서버에 위치를 전달한다.
// updateLocation()과 완전히 같은 경로를 타므로 서버가 실제 진동 명령을 만들어
// /api/haptics 대기열에 넣는다 — 벨트·팔찌가 폴링 중이면 실제로 진동한다.
async function simulateStepArrival(index) {
  if (!state.route || !state.demoMode) return;
  const step = state.route.steps[index];
  if (!step?.location) return;
  if (elements.gpsDebug.hidden) enterNavigationUiState();
  await updateLocation({
    coords: {
      longitude: step.location.longitude,
      latitude: step.location.latitude,
      accuracy: 3,
    },
    timestamp: Date.now(),
  });
}

// 같은 경로를 그대로 두고 진행 상황(진동 이력 포함)만 처음으로 되돌린다. 카카오 경로를
// 다시 조회하지 않아 "경로 생성"보다 훨씬 빠르다 — 시연을 처음부터 다시 돌릴 때 쓴다.
async function resetNavigationProgress() {
  if (!state.route) return;
  elements.resetProgressButton.disabled = true;
  try {
    await api(`/api/navigation/${state.route.routeId}/reset`, { method: "POST" });
    clearStepFocus();
    state.lastAutoStepIndex = -1;
    state.lastKnownStepIndex = null;
    state.gpsFixCount = 0;
    elements.gpsCount.textContent = "0";
    elements.etaBar.hidden = true;
    setGuidance("GPS 안내를 시작하면 다음 회전까지 거리를 표시합니다.", false);
    setStatus(state.demoMode ? "시연 모드 · 처음부터 다시 시작합니다" : "안내 진행 초기화됨");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    elements.resetProgressButton.disabled = false;
  }
}

function renderGpsDebug(position, result) {
  const c = position.coords;
  elements.gpsCoord.textContent = `${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)}`;
  const acc = Math.round(c.accuracy);
  elements.gpsAccuracy.textContent = `±${acc} m`;
  elements.gpsAccuracy.dataset.level = acc <= 15 ? "good" : acc <= 30 ? "ok" : "poor";
  const ageSec = Math.max(0, Math.round((Date.now() - position.timestamp) / 1000));
  elements.gpsAge.textContent = ageSec < 2 ? "방금" : `${ageSec}초 전`;
  if (result) {
    const dist = Math.round(result.distanceFromRouteMeters ?? 0);
    elements.gpsOffRoute.textContent = result.offRoute
      ? `이탈 · 경로에서 ${dist} m`
      : `경로 위 · ${dist} m`;
    elements.gpsOffRoute.dataset.level = result.offRoute ? "poor" : "good";
  }
}

async function updateLocation(position) {
  const location = {
    longitude: position.coords.longitude,
    latitude: position.coords.latitude,
    accuracy_meters: position.coords.accuracy,
  };
  state.gpsFixCount += 1;
  elements.gpsCount.textContent = String(state.gpsFixCount);
  updateUserMarker(location);
  renderGpsDebug(position, null);
  // "현재 이동 경로" 모드에서는 GPS 신호가 올 때마다 화면이 계속 나를 따라온다(따라가기 모드).
  // "전체 경로" 모드에서는 화면이 고정돼 있어야 하니 여기서는 움직이지 않는다.
  if (state.routeViewMode === "live" && state.map && window.kakao?.maps) {
    state.map.panTo(new window.kakao.maps.LatLng(location.latitude, location.longitude));
  }
  try {
    const result = await api(`/api/navigation/${state.route.routeId}/location`, {
      method: "POST",
      body: JSON.stringify(location),
    });
    renderGpsDebug(position, result);
    updateEtaBar(result);
    if (result.completed) {
      setGuidance("목적지에 도착했습니다.", true);
      stopNavigation();
    } else {
      if (typeof result.currentStepIndex === "number") {
        applyAutoStepFocus(result.currentStepIndex);
      }
      const next = result.nextInstruction;
      const routeState = result.offRoute ? "경로 이탈 감지 · " : "";
      const hazardTag =
        next.maneuver === "STAIRS"
          ? "⚠️ 계단 · "
          : next.maneuver === "CROSSWALK"
            ? "🚸 횡단보도 · "
            : "";
      setGuidance(
        `${routeState}${hazardTag}${Math.round(next.distanceMeters)}m 후 ${next.guidance}`,
        true,
      );
    }
    appendHapticCommands(result.commands);
  } catch (error) {
    setGuidance(error.message);
  }
}

function updateUserMarker(location) {
  if (!state.map || !window.kakao?.maps) return;
  const position = new window.kakao.maps.LatLng(location.latitude, location.longitude);

  // 현재 위치는 핀이 아니라 "파란 점"(구글 지도 스타일)으로 — 출발·도착 핀과 확실히 구분.
  if (!state.userMarker) {
    state.userMarker = new window.kakao.maps.CustomOverlay({
      map: state.map,
      position,
      content:
        '<div class="map-user-dot" role="img" aria-label="현재 위치"><span></span></div>',
      xAnchor: 0.5,
      yAnchor: 0.5,
      zIndex: 20,
    });
  } else {
    state.userMarker.setPosition(position);
  }

  // GPS 정확도 반경 원 (accuracy_meters 가 있을 때만)
  const accuracy = Number(location.accuracy_meters);
  if (Number.isFinite(accuracy) && accuracy > 0) {
    if (!state.accuracyCircle) {
      state.accuracyCircle = new window.kakao.maps.Circle({
        map: state.map,
        strokeWeight: 1,
        strokeColor: "#007aff",
        strokeOpacity: 0.35,
        strokeStyle: "solid",
        fillColor: "#007aff",
        fillOpacity: 0.1,
      });
    }
    state.accuracyCircle.setPosition(position);
    state.accuracyCircle.setRadius(accuracy);
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
// 실제 벨트의 비상 버튼이 서버에 알림을 등록하면, 이 페이지가 몇 초마다 폴링해서
// 확인 전까지 배너로 보여준다. 보호자가 이 화면을 열어둔 상태에서만 보이고,
// 아직 백그라운드 푸시는 없다. (웹에서 직접 알림을 쏴보는 시뮬레이터 버튼은
// 팀 요청으로 프론트엔드에서 제거했다 — 필요해지면 /api/emergency POST로 복원 가능.)
// ---------------------------------------------------------------------------

let lastSeenAlertId = null;

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
  pushRouteViewToggleBelowBanner();
}

function hideEmergencyBanner() {
  elements.emergencyBanner.hidden = true;
  lastSeenAlertId = null;
  pushRouteViewToggleBelowBanner();
}

// 위험 배너와 "전체 경로/현재 이동 경로" 토글이 둘 다 지도 위쪽에 떠서, GPS 안내 중
// 위험 알림이 뜨면 토글을 완전히 가려버린다 — 배너가 보일 땐 그 아래로 밀어준다.
function pushRouteViewToggleBelowBanner() {
  if (!elements.routeViewToggle) return;
  if (elements.emergencyBanner.hidden) {
    elements.routeViewToggle.style.top = "";
    return;
  }
  const bannerBottom = elements.emergencyBanner.getBoundingClientRect().bottom;
  elements.routeViewToggle.style.top = `${bannerBottom + 12}px`;
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
