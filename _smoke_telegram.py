"""텔레그램 연결 확인. 봇이 누구인지, 나한테 온 메시지가 있는지 본다."""
import requests

import config
import notify
import storage

storage.init()

print("토큰:", (config.TELEGRAM_TOKEN[:12] + "…") if config.TELEGRAM_TOKEN else "(없음)")

me = notify._call("getMe", {})
if not me:
    raise SystemExit("봇 확인 실패 — 토큰이 틀렸을 수 있다")
print(f"봇 확인됨: @{me.get('username')} ({me.get('first_name')})")

updates = notify._call("getUpdates", {"timeout": 0}) or []
print(f"\n받은 메시지 {len(updates)}건")
found = {}
for u in updates:
    msg = u.get("message") or {}
    chat = msg.get("chat") or {}
    cid = str(chat.get("id") or "")
    if cid:
        found[cid] = f"{chat.get('first_name', '')} {chat.get('username', '')}".strip()
        print(f"  {cid}  {found[cid]}  : {msg.get('text', '')[:40]}")

if found:
    for cid in found:
        storage.add_subscriber(cid)
    print(f"\n구독자로 등록: {list(found)}")
else:
    print("\n아직 봇에게 보낸 메시지가 없다.")
    print("텔레그램에서 봇을 찾아 /start 를 보낸 뒤 다시 실행해라.")
