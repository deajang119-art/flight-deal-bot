"""여행사 파서 점검. 소스별 수집 건수와 샘플을 보여준다."""
import storage, packages

storage.init()
pkgs, health = packages.collect()

print("\n=== 소스별 ===")
for name, n in health.items():
    print(f"  {name}: {n}건")
broken = packages.broken_sources(health)
if broken:
    print(f"  ⚠ 0건 소스(구조 변경 의심): {', '.join(broken)}")

fit = [p for p in pkgs if p.is_fit]
withdc = [p for p in pkgs if p.list_price]
withdest = [p for p in pkgs if p.dest_key]
stay = [p for p in pkgs if p.stay_only]
withdays = [p for p in pkgs if p.days]
print(f"\n총 {len(pkgs)}건 · 자유여행 {len(fit)}건 · 정가표시 {len(withdc)}건 "
      f"· 목적지인식 {len(withdest)}건 · 일수인식 {len(withdays)}건 · 숙박전용 제외 {len(stay)}건")

print("\n=== 자유여행 샘플 ===")
for p in fit[:8]:
    dc = f" (정가 {p.list_price:,})" if p.list_price else ""
    print(f"  [{p.source_ko}] {p.price:,}원{dc} · {p.dest_label or '?'} · {p.title[:56]}")
    print(f"      {p.url}")

print("\n=== 정가 대비 할인 상위 ===")
for p in sorted(withdc, key=lambda x: (x.list_price - x.price) / x.list_price, reverse=True)[:8]:
    pct = (p.list_price - p.price) / p.list_price * 100
    print(f"  -{pct:4.1f}%  {p.price:,} ← {p.list_price:,}  [{p.source_ko}] {p.title[:48]}")

print("\n=== 딜 판정 ===")
deals = packages.evaluate(pkgs)
print(f"기준 -{__import__('config').PACKAGE_DROP_PCT:.0f}% 이상 → {len(deals)}건")
for d in deals[:8]:
    print(f"  -{d.drop_pct:4.1f}% ({d.basis}, 표본{d.samples})  {d.pkg.price:,}원 "
          f"[{d.pkg.source_ko}] {d.pkg.title[:44]}")
