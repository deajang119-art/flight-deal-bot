import storage, weather
from destinations import BY_IATA

storage.init()
for code in ("DPS", "CTS", "BKK", "CDG", "SYD", "HKT"):
    d = BY_IATA[code]
    print(f"== {d.label}  {d.distance_km:.0f}km  window={d.window}")
    for m in ("01", "04", "08", "11"):
        s = weather.score(d, f"2026-{m}-15")
        print(f"   {m}월  score={s['score']}  {s['summary']}")
    print("   best:", weather.best_months(d))
