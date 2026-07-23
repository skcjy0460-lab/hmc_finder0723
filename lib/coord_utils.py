# -*- coding: utf-8 -*-
"""
검진기관 API의 cxVl/cyVl 좌표를 지도에 뿌릴 수 있는 WGS84(위경도)로 변환합니다.

⚠️ 중요: cxVl/cyVl의 실제 좌표계(EPSG)가 Swagger 문서에 명시되어 있지 않습니다.
국민건강보험공단·건강보험심사평가원 계열 공공데이터는 관행적으로
EPSG:5174(Bessel, 중부원점 TM) 또는 WGS84 경위도를 그대로 넣는 경우가 섞여 있습니다.

이 모듈은 아래 순서로 방어적으로 처리합니다.
1. 값이 이미 우리나라 경위도 범위(위도 33~43, 경도 124~132)면 변환 없이 그대로 사용
2. 아니라면 EPSG:5174 → EPSG:4326 변환을 시도
3. 변환 결과도 범위를 벗어나면 None 반환 (지도에는 표시하지 않고 리스트에는 남김)

첫 실제 응답을 받으신 후 지도 핀 위치가 실제 주소와 다르면
DEFAULT_SOURCE_EPSG 값을 5179 / 5181 / 5185 등으로 바꿔가며 확인해보세요.
"""
from __future__ import annotations

from pyproj import Transformer

DEFAULT_SOURCE_EPSG = "EPSG:5174"
_TRANSFORMER = Transformer.from_crs(DEFAULT_SOURCE_EPSG, "EPSG:4326", always_xy=True)

KR_LAT_RANGE = (33.0, 43.0)
KR_LNG_RANGE = (124.0, 132.0)


def _in_korea_wgs84(lat: float, lng: float) -> bool:
    return KR_LAT_RANGE[0] <= lat <= KR_LAT_RANGE[1] and KR_LNG_RANGE[0] <= lng <= KR_LNG_RANGE[1]


def to_wgs84(cx_vl: str | float | None, cy_vl: str | float | None) -> tuple[float, float] | None:
    """cxVl(경도/X), cyVl(위도/Y) 원본 값을 (lat, lng) WGS84로 변환합니다.

    반환값이 None이면 좌표를 신뢰할 수 없다는 뜻이므로 지도에는 표시하지 마세요.
    """
    if cx_vl in (None, "", "0") or cy_vl in (None, "", "0"):
        return None
    try:
        x, y = float(cx_vl), float(cy_vl)
    except (TypeError, ValueError):
        return None

    # 이미 위경도(WGS84)로 들어오는 케이스
    if _in_korea_wgs84(y, x):
        return y, x

    # TM 좌표계로 가정하고 변환 시도
    try:
        lng, lat = _TRANSFORMER.transform(x, y)
    except Exception:
        return None

    if _in_korea_wgs84(lat, lng):
        return lat, lng
    return None
