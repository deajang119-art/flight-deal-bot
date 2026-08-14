"""항공권 API가 왜 거부하는지 확인(진단용).

같은 토큰이 내 PC에서는 되고 깃허브에서는 401 이 났다.
토큰이 잘못 전달된 것인지, 아니면 요청이 온 곳(IP)을 막는 것인지 가른다.
"""
import os

import requests

TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
print(f"토큰 길이: {len(TOKEN)}")
print(f"토큰 앞뒤: {TOKEN[:4]}…{TOKEN[-4:] if len(TOKEN) > 8 else ''}")
print(f"공백 섞임: {TOKEN != TOKEN.strip()}")

try:
    ip = requests.get("https://api.ipify.org", timeout=15).text
    print(f"나가는 IP: {ip}")
except Exception as exc:
    print(f"IP 확인 실패: {exc}")

URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
BASE = {"origin": "ICN", "destination": "BKK", "departure_at": "2026-10",
        "return_at": "2026-10", "currency": "krw", "limit": 3, "one_way": "false"}

print("\n--- 1) 토큰을 주소에 붙여 보내기 (지금 방식) ---")
r = requests.get(URL, params={**BASE, "token": TOKEN}, timeout=25)
print(f"  {r.status_code}  {r.text[:200]}")

print("\n--- 2) 토큰을 헤더로 보내기 ---")
r = requests.get(URL, params=BASE, headers={"X-Access-Token": TOKEN}, timeout=25)
print(f"  {r.status_code}  {r.text[:200]}")

print("\n--- 3) 브라우저인 척하고 헤더로 보내기 ---")
r = requests.get(URL, params=BASE, headers={
    "X-Access-Token": TOKEN,
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
}, timeout=25)
print(f"  {r.status_code}  {r.text[:200]}")

print("\n--- 4) 토큰 없이 (원래 401 이어야 정상) ---")
r = requests.get(URL, params=BASE, timeout=25)
print(f"  {r.status_code}  {r.text[:200]}")
