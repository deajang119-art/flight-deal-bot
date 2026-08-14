"""목적지 공항 코드가 아직 쓸 수 있는지 전수 확인.

공항은 신공항 개항으로 코드가 바뀐다(씨엠립 REP→SAI, 울란바토르 ULN→UBN).
옛 코드를 두면 그 목적지만 조용히 죽는다. 가끔 이걸 돌려 확인한다.
"""
import time

import requests

import config
from destinations import DESTINATIONS

URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
EXTRA = ["SAI", "UBN"]          # 신공항 후보도 같이 본다


def check(code: str) -> tuple[bool, str]:
    params = {"origin": config.ORIGIN, "destination": code,
              "departure_at": "2026-10", "return_at": "2026-10",
              "currency": config.CURRENCY, "limit": 1, "one_way": "false",
              "token": config.TRAVELPAYOUTS_TOKEN}
    try:
        r = requests.get(URL, params=params, timeout=25)
    except requests.RequestException as exc:
        return False, str(exc)[:60]
    if r.status_code == 200:
        n = len(r.json().get("data") or [])
        return True, f"정상 ({n}건)"
    try:
        return False, r.json().get("error", "")[:70]
    except ValueError:
        return False, f"HTTP {r.status_code}"


bad = []
print(f"목적지 {len(DESTINATIONS)}곳 확인\n")
for d in DESTINATIONS:
    ok, msg = check(d.iata)
    if not ok:
        bad.append((d.iata, d.label, msg))
        print(f"  ✗ {d.iata}  {d.label:22s} {msg}")
    time.sleep(0.3)

print(f"\n쓸 수 없는 공항 {len(bad)}곳")
if bad:
    print("\n신공항 후보 확인:")
    for code in EXTRA:
        ok, msg = check(code)
        print(f"  {'✓' if ok else '✗'} {code}  {msg}")
        time.sleep(0.3)
