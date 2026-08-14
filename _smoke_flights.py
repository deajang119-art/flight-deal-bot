"""항공권 조회 확인. 실제로 가격이 들어오는지, 일수 규칙이 걸리는지 본다."""
import datetime as dt

import config
import flights
import storage
from destinations import BY_IATA

storage.init()
print("토큰:", (config.TRAVELPAYOUTS_TOKEN[:8] + "…") if config.TRAVELPAYOUTS_TOKEN else "(없음)")

start = dt.date.today() + dt.timedelta(days=config.SEARCH_START_DAYS)
ym = flights.scan_months(start, 1)[0]
print(f"조회 기준 달: {ym}\n")

earliest = dt.date.today() + dt.timedelta(days=config.SEARCH_START_DAYS)
print(f"출발 가능 최소일: {earliest}\n")

for code in ("FUK", "BKK", "DAD", "CDG", "SYD"):
    dest = BY_IATA[code]
    lo, hi, tier = dest.window
    same = flights.search_travelpayouts(dest, ym)
    cross = flights.search_travelpayouts(dest, ym, return_month=flights.next_month(ym))
    raw = flights.dedupe_offers(same + cross)
    ok = flights.eligible_offers(dest, raw)

    # 왜 떨어졌는지 나눠서 센다
    too_early = sum(1 for o in raw if dt.date.fromisoformat(o.depart_date) < earliest)
    bad_days = sum(1 for o in raw
                   if dt.date.fromisoformat(o.depart_date) >= earliest
                   and not (lo <= o.days <= hi))

    print(f"{dest.label:22s} {dest.distance_km:>6.0f}km  {tier}({lo}~{hi}일)")
    print(f"     같은달 {len(same)}건 + 달넘김 {len(cross)}건 → 중복제거 {len(raw)}건")
    print(f"     탈락: 출발 너무 이름 {too_early}건 · 일수 안 맞음 {bad_days}건 "
          f"→ 통과 {len(ok)}건")
    for o in sorted(ok, key=lambda x: x.price)[:2]:
        print(f"       {o.price:>9,}원  {o.depart_date}~{o.return_date} ({o.days}일) "
              f"{o.airline} 경유{o.transfers}")
