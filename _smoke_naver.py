"""네이버 경로 점검. 알림은 안 보낸다.

여기서 보는 것
  1. 질의가 아직 먹히는가 (네이버가 화면을 개편하면 여기가 먼저 깨진다)
  2. ⚠헤더를 빼면 정말 거부되는가 (CSRF 방어를 우리가 제대로 넘고 있는지)
  3. 얇은 달 기준값 가드가 실제로 무언가를 걸러 내는가
  4. 표 → Offer → 딜 판정까지 이어지는가
"""
import json
import urllib.parse as up

import requests

import config
import deals as deals_mod
import naver
import storage
from destinations import BY_IATA

storage.init()

# 1. 기본 조회 ────────────────────────────────────────────────────────
dest = BY_IATA["CTS"]
rows = naver.fetch(dest.iata)
print(f"1) {dest.label} 조회 {len(rows)}건")
assert rows, "한 건도 못 받았다 — 질의문이나 변수 이름이 바뀌었을 수 있다"
sample = min(rows, key=lambda r: r["minPrice"])
print(f"   최저 {sample['minPrice']:,}원 "
      f"{sample['departureDate']}~{sample['returnDate']} {sample['tripDays']}일 "
      f"{'/'.join(sample['airlineCodes'])} 경유{sample['stops']}")

# 2. 헤더를 빼면 거부되는지 ───────────────────────────────────────────
url = naver.API + "?" + up.urlencode({
    "operationName": "GET_RECOMMEND_BY_CITY",
    "query": naver.QUERY,
    "variables": json.dumps({
        "departureLocationCode": config.NAVER_ORIGIN_CITY,
        "departureLocationType": "city",
        "arrivalLocationCode": "CTS", "arrivalLocationType": "airport",
        "tripType": "RT"}),
})
bare = {k: v for k, v in naver.HEADERS.items()
        if k not in ("x-apollo-operation-name", "Content-Type")}
body = requests.get(url, headers=bare, timeout=30).json()
blocked = bool(body.get("errors"))
print(f"2) 헤더 빼고 요청 → {'거부됨(정상)' if blocked else '⚠그냥 통과함'}")
if blocked:
    print(f"   사유: {body['errors'][0]['message'][:70]}…")

# 3. 얇은 달 가드 ─────────────────────────────────────────────────────
usable = naver.usable_rows(rows)
priced = naver.month_baselines(usable)
print(f"3) 쓸 수 있는 표 {len(usable)}건 · 평소값을 매긴 표 {len(priced)}건 "
      f"(못 매긴 {len(usable) - len(priced)}건 = 표본이 얇은 달)")
assert len(priced) <= len(usable)

# 3-1. 임박 구간 ──────────────────────────────────────────────────────
# ⚠임박 표의 기준선은 반드시 '정상 구간' 값이라야 한다. 임박끼리 비교하면
# 임박 프리미엄이 기준선에 섞여 비싼 게 싼 것으로 보인다.
last = [r for r in usable if naver.is_lastminute(r)]
print(f"3-1) 임박 표 {len(last)}건 (정상 구간 시작 {naver.normal_start()})")
for r in last:
    got = priced.get(id(r))
    if got:
        assert got[3] is True, "임박 표인데 정상 구간 기준선이 붙었다"
        assert "평소" in got[1], got[1]
for r in usable:
    if not naver.is_lastminute(r) and id(r) in priced:
        assert priced[id(r)][3] is False, "정상 표인데 임박으로 잡혔다"
print("     기준선 종류 확인 통과")

# 4. 판정까지 ────────────────────────────────────────────────────────
found = 0
for iata in ("CTS", "FUK", "NRT", "WEH"):
    d = BY_IATA[iata]
    scanned = naver.scan_destination(d)
    got = deals_mod.evaluate_month(d, scanned)
    found += len(got)
    print(f"4) {d.label:14s} 비교 {len(scanned):3d}건 → 딜 {len(got)}건", end="")
    for g in got:
        print(f"  · {g.offer.price:,}원 (평소 {g.baseline:,}, -{g.month_pct:.0f}%) "
              f"{g.offer.depart_date}~{g.offer.return_date} {g.offer.days}일", end="")
        assert g.offer.link.startswith("https://flight.naver.com/"), g.offer.link
    print()

print(f"\n딜 {found}건. 며칠 조용한 게 정상이라 0건이어도 실패는 아니다.")
