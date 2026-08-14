"""스캔 시각 계산 확인. 자정 넘기기와 정각 경계를 본다."""
import datetime as dt
import config
from main import _next_run

times = config.scan_times()
print("설정된 시각:", times)

CASES = [
    "2026-08-14 09:00", "2026-08-14 10:29", "2026-08-14 10:30",
    "2026-08-14 10:31", "2026-08-14 22:29", "2026-08-14 22:30",
    "2026-08-14 22:31", "2026-08-14 23:59",
]
for s in CASES:
    now = dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    nxt = _next_run(times, now)
    gap = (nxt - now).total_seconds() / 3600
    print(f"  지금 {s}  →  다음 {nxt:%m/%d %H:%M}  ({gap:.2f}시간 뒤)")
    assert nxt > now, "다음 실행이 과거면 안 된다"
    assert gap <= 24.0, "24시간을 넘겨 기다리면 안 된다"

print("\n형식이 틀린 값 처리:")
for raw in ("10:30,이상함,25:00,22:30", "", "9"):
    config.SCAN_TIMES = raw
    print(f"  {raw!r:32s} → {config.scan_times()}")
print("\n통과")
