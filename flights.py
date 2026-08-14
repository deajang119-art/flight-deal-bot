"""항공권 가격 조회.

기본 스캐너는 Travelpayouts(아비아세일즈) Flight Data API.
날짜별 최저가를 월 단위로 한 번에 받아오므로 78개 목적지를 훑어도 호출 수가 적다.

Amadeus는 실시간 조회라 호출 수 제한이 빡빡하다. 딜 후보로 뽑힌 소수만
마지막에 재확인하는 검증용으로 쓴다.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, asdict
from typing import Any

import requests

import config
from destinations import Destination

TP_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVIASALES_BASE = "https://www.aviasales.com"

AMADEUS_TOKEN_PATH = "/v1/security/oauth2/token"
AMADEUS_SEARCH_PATH = "/v2/shopping/flight-offers"

# 연속 호출 사이 최소 간격(초). 무료 티어에서 429를 피하려는 안전장치.
_TP_DELAY = 0.35
_last_call = 0.0


@dataclass
class Offer:
    """왕복 1건."""
    origin: str
    destination: str
    depart_date: str          # YYYY-MM-DD
    return_date: str          # YYYY-MM-DD
    days: int                 # 출발일~귀국일 차이
    price: int
    airline: str = ""
    transfers: int = 0
    link: str = ""
    source: str = "travelpayouts"

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def _throttle() -> None:
    global _last_call
    gap = time.monotonic() - _last_call
    if gap < _TP_DELAY:
        time.sleep(_TP_DELAY - gap)
    _last_call = time.monotonic()


def scan_months(start: dt.date, months: int) -> list[str]:
    """'YYYY-MM' 문자열 목록. 오늘 기준 리드타임 이후의 달만."""
    out: list[str] = []
    y, m = start.year, start.month
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _parse_date(value: str) -> str:
    """API가 '2026-09-14T10:20:00+09:00' 같은 형태로 준다. 날짜만 뽑는다."""
    return (value or "")[:10]


def _full_link(link: str) -> str:
    if not link:
        return ""
    if link.startswith("http"):
        return link
    return AVIASALES_BASE + link


def next_month(year_month: str) -> str:
    """'2026-09' → '2026-10'."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    return f"{year + 1:04d}-01" if month == 12 else f"{year:04d}-{month + 1:02d}"


def search_travelpayouts(
    dest: Destination,
    year_month: str,
    origin: str | None = None,
    return_month: str | None = None,
) -> list[Offer]:
    """한 목적지·한 달 출발의 왕복 최저가 목록.

    return_month 를 따로 주면 달을 넘겨 돌아오는 일정을 찾는다.
    """
    if not config.TRAVELPAYOUTS_TOKEN:
        return []

    origin = origin or config.ORIGIN
    params = {
        "origin": origin,
        "destination": dest.iata,
        "departure_at": year_month,
        "return_at": return_month or year_month,
        "unique": "false",
        "sorting": "price",
        "direct": "false",
        "currency": config.CURRENCY,
        "limit": 1000,
        "page": 1,
        "one_way": "false",
        "token": config.TRAVELPAYOUTS_TOKEN,
    }
    _throttle()
    try:
        resp = requests.get(
            TP_URL, params=params, timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
    except requests.RequestException as exc:
        print(f"  [가격] {dest.iata} {year_month} 연결 실패: {exc}")
        return []

    if resp.status_code != 200:
        # 이유를 찍어야 고칠 수 있다. 'airport XXX: not flightable' 은 공항 코드가
        # 신공항으로 바뀐 경우다(씨엠립 REP→SAI, 울란바토르 ULN→UBN).
        try:
            reason = resp.json().get("error") or resp.text[:120]
        except ValueError:
            reason = resp.text[:120]
        print(f"  [가격] {dest.iata} {year_month} 거부({resp.status_code}): {reason}")
        return []

    try:
        payload = resp.json()
    except ValueError as exc:
        print(f"  [가격] {dest.iata} {year_month} 응답을 못 읽음: {exc}")
        return []

    if not payload.get("success", True):
        print(f"  [가격] {dest.iata} {year_month} 응답 오류: {payload.get('error')}")
        return []

    offers: list[Offer] = []
    for item in payload.get("data") or []:
        depart = _parse_date(item.get("departure_at", ""))
        back = _parse_date(item.get("return_at", ""))
        price = item.get("price")
        if not depart or not back or not price:
            continue
        try:
            d0 = dt.date.fromisoformat(depart)
            d1 = dt.date.fromisoformat(back)
        except ValueError:
            continue
        days = (d1 - d0).days
        if days <= 0:
            continue
        offers.append(Offer(
            origin=origin,
            destination=dest.iata,
            depart_date=depart,
            return_date=back,
            days=days,
            price=int(price),
            airline=str(item.get("airline") or ""),
            transfers=int(item.get("transfers") or 0),
            link=_full_link(str(item.get("link") or "")),
        ))
    return offers


def eligible_offers(dest: Destination, offers: list[Offer]) -> list[Offer]:
    """거리 규칙(근거리 2~4일 / 장거리 7~14일)과 리드타임을 통과한 것만."""
    lo, hi, _tier = dest.window
    earliest = dt.date.today() + dt.timedelta(days=config.SEARCH_START_DAYS)
    keep: list[Offer] = []
    for o in offers:
        if not (lo <= o.days <= hi):
            continue
        try:
            if dt.date.fromisoformat(o.depart_date) < earliest:
                continue
        except ValueError:
            continue
        keep.append(o)
    return keep


def scan_destination(dest: Destination) -> list[Offer]:
    """한 목적지를 SEARCH_MONTHS 개월치 전부 훑는다.

    한 달마다 두 번 묻는다. 같은 달 안에서 돌아오는 일정과, 달을 넘겨 돌아오는
    일정을 API가 따로 취급하기 때문이다. 한 번만 물으면 월말 출발 건이 통째로
    빠진다(방콕 9월 기준 26건 중 11건이 그랬다).
    """
    start = dt.date.today() + dt.timedelta(days=config.SEARCH_START_DAYS)
    found: list[Offer] = []
    for ym in scan_months(start, config.SEARCH_MONTHS):
        found.extend(search_travelpayouts(dest, ym))
        found.extend(search_travelpayouts(dest, ym, return_month=next_month(ym)))
    return eligible_offers(dest, dedupe_offers(found))


def dedupe_offers(offers: list[Offer]) -> list[Offer]:
    """같은 날짜 조합은 가장 싼 것만 남긴다."""
    best: dict[tuple[str, str], Offer] = {}
    for o in offers:
        k = (o.depart_date, o.return_date)
        if k not in best or o.price < best[k].price:
            best[k] = o
    return list(best.values())


# ── Amadeus (선택적 검증용) ──────────────────────────────────────────
_amadeus_token: tuple[str, float] | None = None


def _amadeus_access_token() -> str | None:
    global _amadeus_token
    if not (config.AMADEUS_CLIENT_ID and config.AMADEUS_CLIENT_SECRET):
        return None
    if _amadeus_token and _amadeus_token[1] > time.time() + 60:
        return _amadeus_token[0]
    try:
        resp = requests.post(
            f"https://{config.AMADEUS_HOST}{AMADEUS_TOKEN_PATH}",
            data={
                "grant_type": "client_credentials",
                "client_id": config.AMADEUS_CLIENT_ID,
                "client_secret": config.AMADEUS_CLIENT_SECRET,
            },
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  [Amadeus] 토큰 발급 실패: {exc}")
        return None
    token = body.get("access_token")
    if not token:
        return None
    _amadeus_token = (token, time.time() + float(body.get("expires_in", 1500)))
    return token


def verify_amadeus(offer: Offer) -> int | None:
    """그 날짜 왕복의 실시간 최저가. 실패하면 None(=검증 생략)."""
    token = _amadeus_access_token()
    if not token:
        return None
    params = {
        "originLocationCode": offer.origin,
        "destinationLocationCode": offer.destination,
        "departureDate": offer.depart_date,
        "returnDate": offer.return_date,
        "adults": 1,
        "currencyCode": config.CURRENCY.upper(),
        "max": 5,
    }
    try:
        resp = requests.get(
            f"https://{config.AMADEUS_HOST}{AMADEUS_SEARCH_PATH}",
            params=params,
            headers={"Authorization": f"Bearer {token}",
                     "User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
    except (requests.RequestException, ValueError) as exc:
        print(f"  [Amadeus] {offer.destination} 검증 실패: {exc}")
        return None

    prices = []
    for item in data:
        raw = (item.get("price") or {}).get("grandTotal") or (item.get("price") or {}).get("total")
        if raw:
            try:
                prices.append(int(float(raw)))
            except ValueError:
                continue
    return min(prices) if prices else None
