"""네이버 항공권 자료 수집 (가격그래프·추천일정과 같은 자료).

Travelpayouts 는 우리가 처음부터 쓰던 곳이지만 국내 사정을 잘 못 본다.
제주 같은 국내선 LCC 직판은 거의 안 잡히고, 값도 네이버보다 비싸게 나온다
(실측 2026-08-15: 도쿄 네이버 143,971원 vs Travelpayouts 182,235원,
제주 43,066원 vs 115,824원). 그래서 네이버를 함께 본다.

목적지 한 곳당 한 번 물으면 앞으로 1년치 (출발일·귀국일·일수·최저가·항공사·
경유수)를 200~350건 준다. 0.2초면 온다. 이 한 덩어리 안에 '그 달의 다른
날짜들' 이 다 들어 있어서, **과거 이력 없이도 '평소보다 얼마나 싼가'를
그 자리에서 계산할 수 있다.** 이게 Travelpayouts 경로와 가장 다른 점이다.

⚠API 를 두드릴 때 두 가지를 지켜야 한다. 둘 다 실측으로 데였다.
  1. POST 는 nginx 가 503 으로 막는다 → **GET(쿼리스트링)** 으로 물어야 한다.
  2. 헤더 `x-apollo-operation-name` 이 없으면 아폴로 서버가 CSRF 로 보고
     전부 거부한다. 이걸 빠뜨려 81곳 전량 0건이 나온 적이 있다.

질의문은 네이버 JS 번들 안에 글자가 아니라 AST 객체로 박혀 있다. 아래 QUERY 는
그 AST 를 되편 것이다. 화면이 개편돼 안 되면 flight.naver.com 의 JS 를 받아
kind:"Document" 객체에서 minPricesByDate 를 다시 꺼내면 된다.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import time
import urllib.parse as up
from collections import defaultdict

import requests

import config
from destinations import Destination
from flights import Offer

API = "https://flight-api.naver.com/graphql"

QUERY = """query GET_RECOMMEND_BY_CITY($departureLocationCode: String, $departureLocationType: String, $arrivalLocationCode: String, $arrivalLocationType: String, $tripType: String) {
  minPricesByDate(departureLocationCode: $departureLocationCode, departureLocationType: $departureLocationType, arrivalLocationCode: $arrivalLocationCode, arrivalLocationType: $arrivalLocationType, tripType: $tripType) {
    departureLocation { iataCode }
    arrivalLocation { iataCode }
    departureDate
    returnDate
    tripDays
    minPrice
    airlineCodes
    stops
    isDomestic
  }
}"""

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126 Mobile Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://flight.naver.com",
    "Referer": "https://flight.naver.com/",
    "x-apollo-operation-name": "GET_RECOMMEND_BY_CITY",   # ⚠없으면 CSRF 거부
}

# 일수 버킷. 3일과 14일은 값이 다르니 같은 무리로 묶으면 안 된다.
DAY_BUCKETS = [(2, 2), (3, 4), (5, 7), (8, 10), (11, 14), (15, 30)]

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def booking_link(origin: str, dest: str, depart8: str, return8: str,
                 is_domestic: bool) -> str:
    """네이버 예매 화면 주소. 국내선과 국제선은 경로가 다르다."""
    kind = "domestic" if is_domestic else "international"
    return (f"https://flight.naver.com/flights/{kind}/{origin}-{dest}-{depart8}/"
            f"{dest}-{origin}-{return8}?adult=1")


def fetch(dest_iata: str) -> list[dict]:
    """한 목적지의 1년치 날짜별 최저가. 실패하면 빈 목록."""
    variables = {
        "departureLocationCode": config.NAVER_ORIGIN_CITY,
        "departureLocationType": "city",     # ⚠출발은 city, 도착은 airport 라야 나온다
        "arrivalLocationCode": dest_iata,
        "arrivalLocationType": "airport",
        "tripType": "RT",
    }
    url = API + "?" + up.urlencode({
        "operationName": "GET_RECOMMEND_BY_CITY",
        "query": QUERY,
        "variables": json.dumps(variables),
    })
    session = _get_session()
    for attempt in (1, 2, 3):
        try:
            resp = session.get(url, timeout=config.HTTP_TIMEOUT)
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == 3:
                print(f"  [네이버] {dest_iata} 조회 실패: {exc}")
                return []
            time.sleep(attempt * 2)
            continue
        if body.get("errors"):
            # 이유를 찍어야 고칠 수 있다. CSRF 거부면 헤더 문제다.
            reason = json.dumps(body["errors"], ensure_ascii=False)[:160]
            print(f"  [네이버] {dest_iata} 거부: {reason}")
            return []
        return (body.get("data") or {}).get("minPricesByDate") or []
    return []


def _bucket_of(days: int) -> tuple[int, int]:
    for lo, hi in DAY_BUCKETS:
        if lo <= days <= hi:
            return lo, hi
    return 31, 400


def _iso(date8: str) -> str:
    return f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"


def usable_rows(rows: list[dict]) -> list[dict]:
    """리드타임·기간·일수 조건을 통과한 표만."""
    today = dt.date.today()
    earliest = today + dt.timedelta(days=config.SEARCH_START_DAYS)
    latest = today + dt.timedelta(days=int(config.SEARCH_MONTHS * 30.4))
    keep = []
    for r in rows:
        if not (config.NAVER_MIN_DAYS <= r.get("tripDays", 0) <= config.NAVER_MAX_DAYS):
            continue
        try:
            depart = dt.date.fromisoformat(_iso(r["departureDate"]))
        except (ValueError, KeyError):
            continue
        if not (earliest <= depart <= latest):
            continue
        if not r.get("minPrice"):
            continue
        keep.append(r)
    return keep


def month_baselines(rows: list[dict]) -> dict[int, tuple[float, str, int]]:
    """표마다 '그 달의 평소값'을 매긴다. 반환은 id(row) → (평소값, 근거, 표본수).

    같은 목적지라도 3일과 14일은 값이 다르고 직항과 경유도 다르다. 그래서
        같은 출발월 · 같은 일수 · 직항/경유 구분
    이 같은 표들의 중앙값을 평소값으로 쓴다. 그 무리가 얇으면 일수를 버킷으로
    넓히고, 그래도 얇으면 평소값을 말하지 않는다(=판정 안 함).

    ⚠먼 달은 네이버가 가진 표가 몇 장 없어 중앙값이 위로 튄다. 실측에서
    2027년 8월 하노이가 '평소 120만원'으로 잡혀 37만원짜리가 -69% 특가로
    둔갑했다. 그래서 노선 전 기간 중앙값의 몇 배가 넘는 달 기준값은 버린다.
    """
    exact: dict[tuple, list[int]] = defaultdict(list)
    loose: dict[tuple, list[int]] = defaultdict(list)
    whole: dict[tuple, list[int]] = defaultdict(list)
    for r in rows:
        month = r["departureDate"][:6]
        exact[(month, r["tripDays"], r["stops"])].append(r["minPrice"])
        loose[(month, _bucket_of(r["tripDays"]), r["stops"])].append(r["minPrice"])
        whole[(_bucket_of(r["tripDays"]), r["stops"])].append(r["minPrice"])

    out: dict[int, tuple[float, str, int]] = {}
    for r in rows:
        month = r["departureDate"][:6]
        peers = exact[(month, r["tripDays"], r["stops"])]
        basis = f"{int(month[4:])}월 {r['tripDays']}일짜리 일정"
        if len(peers) < config.NAVER_MIN_PEERS:
            lo, hi = _bucket_of(r["tripDays"])
            peers = loose[(month, (lo, hi), r["stops"])]
            basis = f"{int(month[4:])}월 {lo}~{hi}일짜리 일정"
        if len(peers) < config.NAVER_MIN_PEERS:
            continue
        baseline = statistics.median(peers)
        if baseline <= 0:
            continue
        route = whole[(_bucket_of(r["tripDays"]), r["stops"])]
        if len(route) >= 12:
            route_median = statistics.median(route)
            if baseline > route_median * config.NAVER_MAX_BASELINE_RATIO:
                continue          # 표본이 얇아 위로 튄 달 — 못 믿는다
        out[id(r)] = (baseline, basis, len(peers))
    return out


def to_offer(dest: Destination, row: dict) -> Offer:
    origin = (row.get("departureLocation") or {}).get("iataCode") or config.ORIGIN
    depart8, return8 = row["departureDate"], row["returnDate"]
    return Offer(
        origin=origin,
        destination=dest.iata,
        depart_date=_iso(depart8),
        return_date=_iso(return8),
        days=int(row["tripDays"]),
        price=int(row["minPrice"]),
        airline="/".join(row.get("airlineCodes") or []),
        transfers=int(row.get("stops") or 0),
        link=booking_link(origin, dest.iata, depart8, return8,
                          bool(row.get("isDomestic"))),
        source="naver",
    )


def scan_destination(dest: Destination) -> list[tuple[Offer, float, str, int]]:
    """한 목적지에서 (표, 평소값, 근거, 표본수) 목록. 평소값을 못 매긴 표는 뺀다."""
    rows = usable_rows(fetch(dest.iata))
    if not rows:
        return []
    baselines = month_baselines(rows)
    out = []
    for r in rows:
        found = baselines.get(id(r))
        if not found:
            continue
        baseline, basis, peers = found
        out.append((to_offer(dest, r), baseline, basis, peers))
    return out
