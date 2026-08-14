"""거리 계산과 근거리/장거리 분류."""
from __future__ import annotations

import math

import config

# 인천국제공항
ORIGIN_COORDS = {
    "ICN": (37.4602, 126.4407),
    "GMP": (37.5583, 126.7906),
    "PUS": (35.1795, 128.9382),
    "CJU": (33.5113, 126.4930),
    "TAE": (35.8941, 128.6588),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 지점의 대권거리(km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def origin_coords() -> tuple[float, float]:
    return ORIGIN_COORDS.get(config.ORIGIN.upper(), ORIGIN_COORDS["ICN"])


def distance_from_origin(lat: float, lon: float) -> float:
    olat, olon = origin_coords()
    return haversine_km(olat, olon, lat, lon)


def trip_window(distance_km: float) -> tuple[int, int, str]:
    """거리로 여행 일수 범위를 정한다.

    반환값은 (최소일, 최대일, 'near'|'far').
    일수 = 출발일과 귀국일의 차이. 2일이면 1박 2일이 아니라 2박(48시간) 뒤 귀국.
    """
    if distance_km <= config.NEAR_FAR_KM:
        return config.NEAR_MIN_DAYS, config.NEAR_MAX_DAYS, "near"
    return config.FAR_MIN_DAYS, config.FAR_MAX_DAYS, "far"
