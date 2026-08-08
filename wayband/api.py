"""FastAPI endpoints and static accessible map interface."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import PROJECT_ROOT, Settings
from .hazard import HazardDetector, SensorZone
from .haptics import HapticCommand
from .kakao import KakaoApiError
from .models import Coordinate, Place
from .recording import (
    RecordingAlreadyFinishedError,
    RecordingNotFoundError,
    RecordingStore,
    WaypointType,
)
from .service import RouteNotFoundError, WaybandService


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
RECORDED_ROUTES_DIR = PROJECT_ROOT / "recorded_routes"


class CoordinateBody(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)

    def to_domain(self) -> Coordinate:
        return Coordinate(longitude=self.longitude, latitude=self.latitude)


class PlaceBody(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=200)
    address: str = ""
    road_address: str = ""
    phone: str = ""
    place_url: str = ""
    coordinate: CoordinateBody

    def to_domain(self) -> Place:
        return Place(
            place_id=self.id,
            name=self.name,
            address=self.address,
            road_address=self.road_address,
            phone=self.phone,
            place_url=self.place_url,
            coordinate=self.coordinate.to_domain(),
        )


class RouteBody(BaseModel):
    start: PlaceBody
    destination: PlaceBody
    route_mode: Literal["BROAD_FIRST", "SHORTEST", "ACCESSIBLE"] = "ACCESSIBLE"


class LocationBody(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    accuracy_meters: float | None = Field(default=None, ge=0, le=1000)


class TofBody(BaseModel):
    gateway_id: str = Field(default="belt-01", min_length=1, max_length=100)
    front_left_mm: int = Field(ge=0, le=65535)
    front_right_mm: int = Field(ge=0, le=65535)
    left_side_mm: int = Field(ge=0, le=65535)
    right_side_mm: int = Field(ge=0, le=65535)

    def readings(self) -> dict[SensorZone, int]:
        return {
            SensorZone.FRONT_LEFT: self.front_left_mm,
            SensorZone.FRONT_RIGHT: self.front_right_mm,
            SensorZone.LEFT_SIDE: self.left_side_mm,
            SensorZone.RIGHT_SIDE: self.right_side_mm,
        }


class StartRecordingBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    coordinate: CoordinateBody


class RecordingWaypointBody(BaseModel):
    type: Literal["left_turn", "right_turn", "crosswalk", "stairs", "destination"]
    coordinate: CoordinateBody


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_environment()
    app.state.settings = settings
    app.state.service = WaybandService(settings)
    app.state.hazard = HazardDetector(
        warning_mm=settings.tof_warning_mm,
        critical_mm=settings.tof_critical_mm,
        clear_mm=settings.tof_clear_mm,
    )
    app.state.recordings = RecordingStore(RECORDED_ROUTES_DIR)
    yield


app = FastAPI(
    title="WAYBAND prototype API",
    version="1.0.0",
    lifespan=lifespan,
)


def _service(request: Request) -> WaybandService:
    return request.app.state.service


def _recordings(request: Request) -> RecordingStore:
    return request.app.state.recordings


@app.exception_handler(KakaoApiError)
async def kakao_error_handler(_request: Request, exc: KakaoApiError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "입력값을 확인하세요.", "errors": exc.errors()},
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/config")
def public_config(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return {
        "kakaoJavascriptKey": settings.kakao_javascript_key,
        "prepareDistanceMeters": settings.prepare_distance_meters,
        "turnNowDistanceMeters": settings.turn_now_distance_meters,
    }


@app.get("/api/places")
def search_places(
    request: Request,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    center_longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    center_latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
) -> dict[str, object]:
    if (center_longitude is None) != (center_latitude is None):
        raise HTTPException(
            status_code=400,
            detail="중심 좌표는 경도와 위도를 함께 보내야 합니다.",
        )
    center = (
        Coordinate(center_longitude, center_latitude)
        if center_longitude is not None and center_latitude is not None
        else None
    )
    places = _service(request).search_places(query, center=center)
    return {"places": [place.to_public_dict() for place in places]}


@app.post("/api/routes", status_code=201)
def create_route(request: Request, body: RouteBody) -> dict[str, object]:
    route = _service(request).create_route(
        body.start.to_domain(),
        body.destination.to_domain(),
        body.route_mode,
    )
    return route.to_public_dict()


@app.get("/api/routes/{route_id}")
def get_route(request: Request, route_id: str) -> dict[str, object]:
    try:
        return _service(request).route(route_id).to_public_dict()
    except RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.") from exc


@app.post("/api/navigation/{route_id}/location")
def update_location(
    request: Request,
    route_id: str,
    body: LocationBody,
) -> dict[str, object]:
    try:
        return _service(request).update_location(
            route_id,
            Coordinate(body.longitude, body.latitude),
            body.accuracy_meters,
        )
    except RouteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.") from exc


@app.post("/api/tof")
def update_tof(request: Request, body: TofBody) -> dict[str, object]:
    detector: HazardDetector = request.app.state.hazard
    result = detector.update(body.gateway_id, body.readings())
    command_objects = cast(list[HapticCommand], result.pop("_commandObjects"))
    _service(request).commands.publish(command_objects)
    return result


@app.get("/api/haptics")
def pending_haptics(
    request: Request,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, object]:
    items = _service(request).commands.after(after_sequence, limit)
    return {
        "commands": [item.to_public_dict() for item in items],
        "lastSequence": items[-1].sequence if items else after_sequence,
    }


# ---------------------------------------------------------------------------
# 경로 기록 모드 (Route recording mode)
#
# A companion walks the real route once with the visually impaired user and
# taps a button at each turn/crosswalk/stairs/destination. Each tap sends the
# phone's current GPS coordinate plus the point type; on "경로 저장" the
# tagged points are written to recorded_routes/route_<id>.json in the shape
# the belt (Raspberry Pi) is expected to read for guidance mode. This service
# does not itself run turn-by-turn guidance against these recordings yet.
# ---------------------------------------------------------------------------


@app.post("/api/recordings", status_code=201)
def start_recording(request: Request, body: StartRecordingBody) -> dict[str, object]:
    try:
        session = _recordings(request).start(body.name, body.coordinate.to_domain())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_public_dict()


@app.get("/api/recordings")
def list_saved_recordings(request: Request) -> dict[str, object]:
    return {"routes": _recordings(request).list_saved()}


@app.get("/api/recordings/{recording_id}")
def get_recording(request: Request, recording_id: str) -> dict[str, object]:
    try:
        return _recordings(request).get(recording_id).to_public_dict()
    except RecordingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.") from exc


@app.post("/api/recordings/{recording_id}/waypoints", status_code=201)
def add_recording_waypoint(
    request: Request,
    recording_id: str,
    body: RecordingWaypointBody,
) -> dict[str, object]:
    try:
        waypoint = _recordings(request).add_waypoint(
            recording_id,
            WaypointType(body.type),
            body.coordinate.to_domain(),
        )
    except RecordingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.") from exc
    except RecordingAlreadyFinishedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return waypoint.to_public_dict()


@app.post("/api/recordings/{recording_id}/finish")
def finish_recording(request: Request, recording_id: str) -> dict[str, object]:
    try:
        return _recordings(request).finish(recording_id)
    except RecordingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.") from exc
    except RecordingAlreadyFinishedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
