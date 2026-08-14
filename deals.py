"""딜 판정.

'싸다'의 기준은 그 노선의 평소 가격이다. 두 가지를 함께 본다.

1. 같은 노선 다른 날짜들의 가격  → 특정 날짜만 유난히 싼 경우를 잡는다
2. 지금까지 관측해 온 과거 가격  → 노선 전체가 세일 중인 경우를 잡는다

둘을 한 표본으로 합쳐 중앙값을 내고, 그보다 DEAL_DROP_PCT 이상 싸면 딜로 본다.
여기에 '갔을 때 날씨' 점수를 하한선으로 걸어 우기·폭염·혹한기를 걸러낸다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import config
import storage
import weather
from destinations import Destination
from flights import Offer

# 노선당 이만큼은 관측돼야 '평소 가격'을 말할 수 있다
MIN_SAMPLES = 8
# 한 목적지에서 최대 몇 건까지 후보로 올릴지
MAX_PER_DEST = 1


@dataclass
class Deal:
    offer: Offer
    dest: Destination
    baseline: float
    drop_pct: float
    weather_score: float
    weather_summary: str
    samples: int
    is_record_low: bool = False
    verified_price: int | None = None
    rank: float = 0.0
    notes: list[str] = field(default_factory=list)
    basis: str = "평소가"           # 무엇과 비교해 걸렸는지
    week_low_pct: float = 0.0      # 최근 7일 최저가 대비 하락폭

    @property
    def key(self) -> str:
        return f"{self.offer.destination}|{self.offer.depart_date}|{self.offer.return_date}"

    @property
    def is_jackpot(self) -> bool:
        return (self.drop_pct >= config.JACKPOT_DROP_PCT
                or self.week_low_pct >= config.JACKPOT_DROP_PCT)

    @property
    def headline_pct(self) -> float:
        """제목에 쓸 하락폭. 무엇에 걸려 알림이 났는지와 같은 기준이어야 한다."""
        return self.week_low_pct if self.basis != "평소가" else self.drop_pct

    @property
    def saved(self) -> int:
        return int(self.baseline - self.offer.price)


def _baseline_pool(dest: Destination, offers: list[Offer]) -> list[int]:
    """평소 가격을 재는 표본. 이번 스캔 + 최근 90일 관측 이력."""
    current = [o.price for o in offers]
    history = storage.historical_prices(config.ORIGIN, dest.iata, days_back=90)
    return current + history


def _rank(drop_pct: float, weather_score: float, transfers: int) -> float:
    """알림 우선순위. 싼 정도가 주고, 날씨와 직항 여부가 보조."""
    score = drop_pct
    score += (weather_score - 70.0) * 0.40
    if transfers == 0:
        score += 4.0          # 근거리 2~4일 일정에서 경유는 실제로 손해가 크다
    elif transfers >= 2:
        score -= 6.0
    return round(score, 2)


def evaluate(dest: Destination, offers: list[Offer]) -> list[Deal]:
    """한 목적지의 후보 목록에서 딜을 뽑는다."""
    if not offers:
        return []

    pool = _baseline_pool(dest, offers)
    if len(pool) < MIN_SAMPLES:
        return []

    baseline = storage.median(pool)
    if not baseline or baseline <= 0:
        return []

    record_low = min(pool)
    threshold = baseline * (1.0 - config.DEAL_DROP_PCT / 100.0)

    # 스카이스캐너 Drops 기준선. 최근 7일 최저가에서 더 떨어졌는지 본다.
    wk_low, wk_n = storage.week_low(config.ORIGIN, dest.iata, config.WEEK_LOW_DAYS)
    wk_threshold = None
    if wk_low and wk_n >= MIN_SAMPLES:
        wk_threshold = wk_low * (1.0 - config.WEEK_LOW_DROP_PCT / 100.0)

    # 둘 중 느슨한 쪽까지는 후보로 본다(어느 하나만 걸려도 딜이므로)
    cutoff = max(threshold, wk_threshold or 0.0)

    found: list[Deal] = []
    for o in sorted(offers, key=lambda x: x.price):
        if o.price > cutoff:
            break                      # 가격순 정렬이라 여기서 끊어도 된다

        by_median = o.price <= threshold
        by_week_low = wk_threshold is not None and o.price <= wk_threshold
        if not (by_median or by_week_low):
            continue

        w = weather.score(dest, o.depart_date)
        w_score = w["score"]
        if w_score is None:
            # 기후 자료를 못 받은 목적지는 날씨 조건을 통과시키되 표시는 남긴다
            w_score = float(config.MIN_WEATHER_SCORE)
        elif w_score < config.MIN_WEATHER_SCORE:
            continue

        drop = (baseline - o.price) / baseline * 100.0
        wk_drop = ((wk_low - o.price) / wk_low * 100.0) if wk_low else 0.0

        deal = Deal(
            offer=o,
            dest=dest,
            baseline=round(baseline),
            drop_pct=round(drop, 1),
            weather_score=w_score,
            weather_summary=w["summary"],
            samples=len(pool),
            is_record_low=o.price <= record_low,
            basis="평소가" if by_median else f"{config.WEEK_LOW_DAYS}일 최저가",
            week_low_pct=round(wk_drop, 1),
        )
        deal.rank = _rank(deal.drop_pct, w_score, o.transfers)
        if by_week_low:
            # 이미 싼 값에서 또 떨어진 것이라 중앙값 대비보다 신호가 강하다
            deal.rank += 8.0
            deal.notes.append(
                f"{config.WEEK_LOW_DAYS}일 최저가({wk_low:,}원)보다 {wk_drop:.0f}% 더 쌈")
        if deal.is_record_low:
            deal.notes.append("관측 이래 최저가")
        if o.transfers == 0:
            deal.notes.append("직항")
        found.append(deal)
        if len(found) >= MAX_PER_DEST:
            break

    return found


def filter_new(candidates: list[Deal]) -> list[Deal]:
    """쿨다운에 걸린 건 빼고, 순위대로 잘라낸다."""
    fresh = [
        d for d in candidates
        if not storage.recently_alerted(d.key, config.ALERT_COOLDOWN_HOURS, d.offer.price)
    ]
    fresh.sort(key=lambda d: d.rank, reverse=True)
    return fresh[: config.MAX_ALERTS_PER_SCAN]


def verify(deals: list[Deal]) -> list[Deal]:
    """Amadeus 키가 있으면 발송 직전에 실시간 가격으로 한 번 더 확인한다."""
    if not (config.AMADEUS_CLIENT_ID and config.AMADEUS_CLIENT_SECRET):
        return deals

    import flights

    kept: list[Deal] = []
    for d in deals:
        actual = flights.verify_amadeus(d.offer)
        if actual is None:
            kept.append(d)                     # 검증 불가는 통과
            continue
        d.verified_price = actual
        # 실시간가가 캐시가보다 30% 넘게 비싸면 이미 팔린 가격이다
        if actual > d.offer.price * 1.30:
            print(f"  [검증] {d.dest.label} 탈락: 캐시 {d.offer.price:,} → 실시간 {actual:,}")
            continue
        if actual > d.offer.price:
            d.notes.append(f"실시간 {actual:,}원")
        kept.append(d)
    return kept


def summarize(deals: list[Deal]) -> str:
    if not deals:
        return "조건에 맞는 딜 없음"
    best = deals[0]
    return (f"{len(deals)}건 · 최고 {best.dest.label} "
            f"{best.offer.price:,}원 (-{best.drop_pct:.0f}%)")


def today_iso() -> str:
    return dt.date.today().isoformat()


def as_dict(deal: Deal) -> dict[str, Any]:
    return {
        "destination": deal.dest.label,
        "iata": deal.offer.destination,
        "depart": deal.offer.depart_date,
        "return": deal.offer.return_date,
        "days": deal.offer.days,
        "price": deal.offer.price,
        "baseline": deal.baseline,
        "drop_pct": deal.drop_pct,
        "weather": deal.weather_score,
        "link": deal.offer.link,
    }
