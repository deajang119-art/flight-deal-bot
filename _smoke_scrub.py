"""공개 저장소에 올려도 되는 DB인지 확인.

가격 이력은 올려야 하지만 내 텔레그램 ID는 올리면 안 된다.
파일 전체를 바이트로 훑어 개인 정보 흔적을 찾는다(지운 행이 빈 공간에
남아 있을 수도 있으므로 테이블 조회만으로는 부족하다).
"""
import os
import sqlite3
import sys

import config

SECRETS = [s for s in (
    os.environ.get("TELEGRAM_CHAT_ID", ""),
    config.TELEGRAM_TOKEN,
    config.TRAVELPAYOUTS_TOKEN,
) if s]

path = config.DB_PATH
print(f"검사 대상: {path}")
print(f"크기: {path.stat().st_size / 1024:,.0f} KB\n")

conn = sqlite3.connect(path)
print("테이블 내용:")
for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
    n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    flag = "  ← 비어 있어야 함" if name == "subscribers" else ""
    print(f"  {name:16s} {n:>7,}건{flag}")
conn.close()

raw = path.read_bytes()
print("\n파일 전체 바이트 검사:")
bad = False
for secret in SECRETS:
    hit = secret.encode() in raw
    print(f"  {secret[:10]}… : {'!!! 발견됨' if hit else '없음'}")
    bad = bad or hit

if not SECRETS:
    print("  (비교할 값이 없다. .env 를 읽지 못했다)")

print("\n" + ("!!! 공개 금지 — 개인 정보가 남아 있다" if bad else "공개해도 안전"))
sys.exit(1 if bad else 0)
