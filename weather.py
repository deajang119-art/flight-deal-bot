"""목적지의 '갔을 때 날씨' 점수.

Open-Meteo 아카이브 API(무료, 키 불필요)로 최근 3년 실측 일별 자료를 받아
월별 기후 평년값을 직접 계산한다. 결과는 SQLite에 30일 캐시.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import requests

import config
import storage
from destinations import Destination

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# 최근 3년. 아카이브는 며칠 지연되므로 완결된 연도만 쓴다.
_LAST_FULL_YEAR = dt.date.today().year - 1
CLIMATE_START = f"{_LAST_FULL_YEAR - 2}-01-01"
CLIMATE_END = f"{_LAST_FULL_YEAR}-12-31"

RAIN_DAY_MM = 1.0          # 이 이상 오면 '비 온 날'
IDEAL_LOW, IDEAL_HIGH = 18.0, 27.0   # 체감 쾌적 구간(°C)


def _fetch_climate(dest: Destination) -> dict[str, dict[str, float]] | None:
    params = {
        "latitude": dest.lat,
        "longitude": dest.lon,
        "start_date": CLIMATE_START,
        "end_date": CLIMATE_END,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto",
    }
    try:
        resp = requests.get(
            ARCHIVE_URL, params=params, timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        resp.raise_for_status()
        daily = resp.json().get("daily") or {}
    except (requests.RequestException, ValueError) as exc:
        print(f"  [기후] {dest.iata} 조회 실패: {exc}")
        return None

    times = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    prcp = daily.get("precipitation_sum") or []
    if not times:
        return None

    buckets: dict[str, dict[str, list[float]]] = {}
    for i, day in enumerate(times):
        month = day[5:7]
        b = buckets.setdefault(month, {"tmax": [], "tmin": [], "prcp": []})
        if i < len(tmax) and tmax[i] is not None:
            b["tmax"].append(float(tmax[i]))
        if i < len(tmin) and tmin[i] is not None:
            b["tmin"].append(float(tmin[i]))
        if i < len(prcp) and prcp[i] is not None:
            b["prcp"].append(float(prcp[i]))

    out: dict[str, dict[str, float]] = {}
    for month, b in buckets.items():
        if not b["tmax"] or not b["tmin"]:
            continue
        n_days = len(b["prcp"]) or 1
        rain_days = sum(1 for p in b["prcp"] if p >= RAIN_DAY_MM)
        n_years = max(1, len(b["tmax"]) // 28)
        out[month] = {
            "tmax": round(sum(b["tmax"]) / len(b["tmax"]), 1),
            "tmin": round(sum(b["tmin"]) / len(b["tmin"]), 1),
            "rain_ratio": round(rain_days / n_days, 3),
            "precip_mm": round(sum(b["prcp"]) / n_years, 1),
        }
    return out or None


def climate_for(dest: Destination) -> dict[str, dict[str, float]] | None:
    cached = storage.get_climate(dest.iata)
    if cached:
        return cached
    fresh = _fetch_climate(dest)
    if fresh:
        storage.put_climate(dest.iata, fresh)
    return fresh


def score(dest: Destination, depart_date: str) -> dict[str, Any]:
    """출발 월 기준 날씨 점수(0~100)와 사람이 읽는 요약."""
    month = depart_date[5:7]
    climate = climate_for(dest)
    if not climate or month not in climate:
        return {"score": None, "summary": "기후 자료 없음", "detail": {}}

    c = climate[month]
    tmax, tmin = c["tmax"], c["tmin"]
    rain_ratio = c["rain_ratio"]
    feel = tmax * 0.6 + tmin * 0.4

    penalty = 0.0
    if feel < IDEAL_LOW:
        penalty += (IDEAL_LOW - feel) * 4.0
    elif feel > IDEAL_HIGH:
        penalty += (feel - IDEAL_HIGH) * 6.0      # 더위가 여행 만족도를 더 깎는다

    if rain_ratio > 0.20:
        penalty += (rain_ratio - 0.20) * 150.0    # 우기·장마·태풍철 배제

    if tmax >= 34:
        penalty += 15.0
    if tmax <= 2:
        # 설경이 목적인 곳은 추위 벌점을 절반만
        penalty += 10.0 * (0.5 if "설경" in dest.tags else 1.0)

    value = max(0.0, min(100.0, 100.0 - penalty))

    if rain_ratio >= 0.45:
        mood = "우기"
    elif tmax >= 34:
        mood = "폭염"
    elif tmax <= 2:
        mood = "혹한"
    elif value >= 85:
        mood = "쾌적"
    elif value >= 70:
        mood = "무난"
    else:
        mood = "애매"

    summary = (
        f"{mood} · 낮 {tmax:.0f}° / 밤 {tmin:.0f}° · "
        f"비 오는 날 {rain_ratio * 100:.0f}%"
    )
    return {
        "score": round(value, 1),
        "summary": summary,
        "detail": {"tmax": tmax, "tmin": tmin, "rain_ratio": rain_ratio,
                   "precip_mm": c["precip_mm"], "feel": round(feel, 1)},
    }


def best_months(dest: Destination, top: int = 3) -> list[tuple[str, float]]:
    """그 목적지의 날씨가 가장 좋은 달(참고용)."""
    climate = climate_for(dest)
    if not climate:
        return []
    year = dt.date.today().year
    scored = []
    for month in climate:
        s = score(dest, f"{year}-{month}-15")
        if s["score"] is not None:
            scored.append((month, s["score"]))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top]


def warm_cache(dests: list[Destination]) -> int:
    """모든 목적지의 기후 자료를 미리 받아 둔다."""
    ok = 0
    for d in dests:
        if climate_for(d):
            ok += 1
    return ok
