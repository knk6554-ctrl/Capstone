"""Small Kakao REST client for place search and official walking routes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Coordinate, Place


class KakaoApiError(RuntimeError):
    """Raised when Kakao returns an HTTP, transport, or schema error."""


class KakaoClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://dapi.kakao.com",
        timeout_seconds: float = 10,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Kakao REST API 키가 비어 있습니다.")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def get_json(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self._base_url}{normalized_path}?{urlencode(params)}"
        request = Request(
            url,
            headers={"Authorization": f"KakaoAK {self._api_key}"},
            method="GET",
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise KakaoApiError(
                f"카카오 API가 HTTP {exc.code}을 반환했습니다: {detail}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise KakaoApiError(f"카카오 API 연결에 실패했습니다: {reason}") from exc

        try:
            result = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise KakaoApiError("카카오 API 응답이 JSON이 아닙니다.") from exc
        if not isinstance(result, dict):
            raise KakaoApiError("카카오 API 최상위 응답이 객체가 아닙니다.")
        return result

    def search_places(
        self,
        query: str,
        *,
        center: Coordinate | None = None,
        size: int = 5,
    ) -> list[Place]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("장소 검색어를 입력하세요.")
        if not 1 <= size <= 15:
            raise ValueError("장소 검색 개수는 1~15 범위여야 합니다.")

        params: dict[str, Any] = {"query": normalized_query, "size": size}
        if center is not None:
            params.update(
                {
                    "x": center.longitude,
                    "y": center.latitude,
                    "radius": 20000,
                    "sort": "distance",
                }
            )

        payload = self.get_json("/v2/local/search/keyword.json", params)
        documents = payload.get("documents")
        if not isinstance(documents, list):
            raise KakaoApiError("장소 검색 응답에 documents 배열이 없습니다.")
        return [
            Place.from_kakao_document(document)
            for document in documents
            if isinstance(document, dict)
        ]

    def request_walking_route(
        self,
        start: Place,
        destination: Place,
        *,
        route_mode: str = "ACCESSIBLE",
    ) -> dict[str, Any]:
        allowed_modes = {"BROAD_FIRST", "SHORTEST", "ACCESSIBLE"}
        if route_mode not in allowed_modes:
            raise ValueError(
                "route_mode는 BROAD_FIRST, SHORTEST, ACCESSIBLE 중 하나여야 합니다."
            )

        payload = self.get_json(
            "/v2/routing/walk",
            {
                "start_x": start.coordinate.longitude,
                "start_y": start.coordinate.latitude,
                "end_x": destination.coordinate.longitude,
                "end_y": destination.coordinate.latitude,
                "s_name": start.name,
                "e_name": destination.name,
                "input_coord": "WGS84",
                "output_coord": "WGS84",
                "route_mode": route_mode,
            },
        )
        status = payload.get("status")
        if status != "OK":
            raise KakaoApiError(f"도보 경로 탐색에 실패했습니다(status={status!r}).")
        if not isinstance(payload.get("route"), dict):
            raise KakaoApiError("도보 경로 응답에 route 객체가 없습니다.")
        return payload
