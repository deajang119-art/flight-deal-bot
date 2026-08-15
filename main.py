"""실행 진입점.

  python main.py scan     한 번 훑고 알림 보내기
  python main.py loop     정해진 시각에 계속 (SCAN_TIMES, 기본 10:30·22:30)
  python main.py packages 여행사 특가만 훑기 (항공권 API 키 없이도 됨)
  python main.py hours    새 최저가가 몇 시에 나왔는지 (스캔 시각 정하는 근거)
  python main.py warmup   목적지 기후 자료 미리 받아두기
  python main.py listen   텔레그램 명령 받기 (/start 구독 등록)
  python main.py status   설정과 수집 현황 보기
  python main.py test     텔레그램 연결 확인
"""
from __future__ import annotations

import datetime as dt
import sys
import time
import traceback

import config
import deals as deals_mod
import destinations
import flights
import naver
import notify
import packages as pkg_mod
import storage
import weather
from deals import Deal
from packages import PackageDeal


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ── 항공권 ───────────────────────────────────────────────────────────
def scan_travelpayouts(targets: list) -> list[Deal]:
    """이력 기반 경로 — 중앙값 대비, 7일 최저가 대비(Drops 방식)."""
    if not config.TRAVELPAYOUTS_TOKEN:
        _log("항공권: TRAVELPAYOUTS_TOKEN이 없어 건너뛴다")
        return []

    # ⚠국내선은 Travelpayouts 가 LCC 직판을 거의 못 봐서 값이 두 배로 나온다.
    # 잘못된 '평소가'를 만들지 않도록 이 경로에서는 뺀다(네이버가 본다).
    targets = [d for d in targets if "국내" not in d.tags]
    _log(f"항공권(Travelpayouts): {len(targets)}곳 × {config.SEARCH_MONTHS}개월 훑는 중")
    candidates: list[Deal] = []
    total_obs = 0
    for i, dest in enumerate(targets, 1):
        offers = flights.scan_destination(dest)
        if not offers:
            continue
        total_obs += storage.save_observations([o.as_row() for o in offers])
        candidates.extend(deals_mod.evaluate(dest, offers))
        if i % 20 == 0:
            _log(f"  {i}/{len(targets)}곳 · 관측 {total_obs}건 · 후보 {len(candidates)}건")
    _log(f"항공권(Travelpayouts): 관측 {total_obs}건 → 후보 {len(candidates)}건")
    return candidates


def scan_naver(targets: list) -> list[Deal]:
    """네이버 경로 — 같은 달 평소가 대비. 이력이 필요 없어 첫날부터 제대로 판정한다.

    ⚠관측을 DB에 쌓지 않는다. 한 번에 목적지당 200~350건씩 오는데(전체 약
    19,000건) 그대로 저장하면 매 실행마다 저장소에 되커밋하는 DB가 하루 만에
    몇 배로 불어난다. 이 경로는 판정에 이력이 필요 없으므로 안 쌓아도 된다.
    """
    if not config.NAVER_ENABLED:
        return []

    _log(f"항공권(네이버): {len(targets)}곳 훑는 중")
    candidates: list[Deal] = []
    total_rows = 0
    for i, dest in enumerate(targets, 1):
        priced = naver.scan_destination(dest)
        total_rows += len(priced)
        candidates.extend(deals_mod.evaluate_month(dest, priced))
        if i % 20 == 0:
            _log(f"  {i}/{len(targets)}곳 · 비교 {total_rows}건 · 후보 {len(candidates)}건")
        time.sleep(0.25)          # 네이버 서버를 몰아치지 않는다
    _log(f"항공권(네이버): 비교 {total_rows}건 → 후보 {len(candidates)}건")
    return candidates


def scan_flights() -> list[Deal]:
    targets = destinations.DESTINATIONS
    candidates = scan_travelpayouts(targets) + scan_naver(targets)
    fresh = deals_mod.filter_new(candidates)
    _log(f"항공권: 후보 {len(candidates)}건 → 쿨다운 통과 {len(fresh)}건")
    return deals_mod.verify(fresh)


# ── 여행사 ───────────────────────────────────────────────────────────
def scan_packages() -> tuple[list[PackageDeal], list[str]]:
    if not config.PACKAGE_ENABLED:
        return [], []
    _log("여행사: 자유여행 특가 훑는 중")
    pkgs, health = pkg_mod.collect()
    broken = pkg_mod.broken_sources(health)
    found = pkg_mod.evaluate(pkgs)
    _log(f"여행사: 상품 {len(pkgs)}건 → 특가 {len(found)}건")
    return pkg_mod.filter_new(found), broken


# ── 한 바퀴 ──────────────────────────────────────────────────────────
def run_once() -> int:
    storage.init()
    flight_deals = scan_flights()
    package_deals, broken = scan_packages()

    if not flight_deals and not package_deals:
        _log("보낼 알림 없음")
    else:
        for d in flight_deals:
            _log(f"  ✈️ {d.dest.label} {d.offer.price:,}원 -{d.drop_pct:.0f}% "
                 f"({d.offer.depart_date}~{d.offer.return_date})")
        for d in package_deals:
            _log(f"  🏝 [{d.pkg.source_ko}] {d.pkg.price:,}원 -{d.drop_pct:.0f}% "
                 f"{d.pkg.title[:40]}")

    sent = notify.send_deals(flight_deals, package_deals)
    if broken:
        notify.send_health_warning(broken)
    _log(f"발송 {sent}건")

    storage.set_meta("last_scan", str(int(time.time())))
    storage.purge_old()
    storage.purge_old_packages()
    return sent


def _next_run(times: list[tuple[int, int]], now: dt.datetime) -> dt.datetime:
    """오늘 남은 시각 중 가장 이른 것, 없으면 내일 첫 시각."""
    for hour, minute in times:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now:
            return candidate
    hour, minute = times[0]
    return (now + dt.timedelta(days=1)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


def run_loop() -> None:
    times = config.scan_times()

    if not times:
        interval = max(0.5, config.SCAN_INTERVAL_HOURS) * 3600
        _log(f"{config.SCAN_INTERVAL_HOURS:g}시간마다 반복. 멈추려면 Ctrl+C")
        while True:
            _safe_scan()
            _log(f"다음 스캔까지 {config.SCAN_INTERVAL_HOURS:g}시간 대기")
            time.sleep(interval)

    listed = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    _log(f"하루 {len(times)}번 · {listed} 에 실행. 멈추려면 Ctrl+C")
    while True:
        target = _next_run(times, dt.datetime.now())
        wait = (target - dt.datetime.now()).total_seconds()
        _log(f"다음 스캔 {target:%m/%d %H:%M} (약 {wait / 3600:.1f}시간 뒤)")
        while wait > 0:
            time.sleep(min(wait, 300))      # 잘게 자야 Ctrl+C가 바로 먹는다
            wait = (target - dt.datetime.now()).total_seconds()
        _safe_scan()


def _safe_scan() -> None:
    try:
        run_once()
    except KeyboardInterrupt:
        raise
    except Exception:
        _log("스캔 중 오류 — 다음 차례에 다시 시도한다")
        traceback.print_exc()


# ── 텔레그램 명령 ────────────────────────────────────────────────────
def _handle(chat_id: str, command: str) -> None:
    if command in ("/start", "start"):
        storage.add_subscriber(chat_id)
        notify.send("알림을 켰다.\n\n" + notify.HELP, chat_id)
        _log(f"구독 등록: {chat_id}")
    elif command in ("/stop", "stop"):
        storage.remove_subscriber(chat_id)
        notify.send("알림을 껐다. 다시 받으려면 /start", chat_id)
    elif command in ("/status", "status"):
        notify.send(status_text(), chat_id)
    elif command in ("/now", "now"):
        notify.send("지금 한 번 훑는다. 몇 분 걸린다.", chat_id)
        run_once()
    else:
        notify.send(notify.HELP, chat_id)


def status_text() -> str:
    storage.init()
    s = storage.stats()
    last = storage.get_meta("last_scan", "")
    when = time.strftime("%m/%d %H:%M", time.localtime(int(last))) if last else "아직 없음"
    return (
        "<b>현재 설정</b>\n" + notify.esc(config.summary()) +
        f"\n\n<b>수집 현황</b>\n"
        f"항공권 관측 {s['observations']:,}건 · 노선 {s['routes']}개\n"
        f"여행사 상품 관측 {s['packages']:,}건\n"
        f"마지막 스캔 {when}"
    )


# ── 진입점 ───────────────────────────────────────────────────────────
def main() -> int:
    command = (sys.argv[1] if len(sys.argv) > 1 else "scan").lower()
    storage.init()

    missing = config.missing_required()
    if command in ("scan", "loop") and missing:
        print("설정이 비어 있다: " + ", ".join(missing))
        print(".env 파일을 채워라 (.env.example 참고).")
        if not config.PACKAGE_ENABLED:
            return 1
        print("→ 여행사 특가만 진행한다.\n")

    if command == "scan":
        run_once()
    elif command == "loop":
        run_loop()
    elif command == "packages":
        pkgs, health = pkg_mod.collect()
        found = pkg_mod.evaluate(pkgs)
        print(f"\n상품 {len(pkgs)}건 → 특가 {len(found)}건 "
              f"(기준 -{config.PACKAGE_DROP_PCT:.0f}%)")
        for d in found[:20]:
            print(f"  -{d.drop_pct:4.1f}%  {d.pkg.price:>9,}원  "
                  f"[{d.pkg.source_ko}] {d.pkg.title[:52]}")
            print(f"          {d.pkg.url}")
        if not found:
            # 기준에 못 미쳐도 상위권은 보여 준다. 수집이 죽었는지 아니면
            # 정말 싼 게 없는지 눈으로 구분할 수 있어야 한다.
            near = pkg_mod.evaluate_all(pkgs)[:5]
            if near:
                print("\n기준에는 못 미친 상위권:")
                for d in near:
                    print(f"  -{d.drop_pct:4.1f}%  {d.pkg.price:>9,}원  "
                          f"[{d.pkg.source_ko}] {d.pkg.title[:52]}")
        for name in pkg_mod.broken_sources(health):
            print(f"  ⚠ {name}: 0건 — 사이트 구조 변경 의심")
    elif command == "scrub":
        n = storage.scrub_private()
        print(f"개인 정보 지움 (구독자 {n}건). 이제 DB를 공개해도 된다.")
    elif command == "hours":
        hours = storage.new_low_hours()
        total = sum(hours.values())
        if total < 20:
            print(f"아직 표본이 적다(새 최저가 {total}건). 며칠 더 돌린 뒤에 보는 게 낫다.")
        print(f"\n새 최저가가 나온 시각 (최근 60일 · 총 {total}건)")
        print("스캔 시각을 여기에 맞추면 된다.\n")
        peak = max(hours.values()) if hours else 0
        scheduled = {h for h, _ in config.scan_times()}
        for hour in range(24):
            n = hours.get(hour, 0)
            bar = "█" * round(n / peak * 40) if peak else ""
            mark = " ←" if hour in scheduled else ""
            print(f"  {hour:02d}시  {n:>4}  {bar}{mark}")
        print("\n(← 는 지금 설정된 스캔 시각)")
    elif command == "warmup":
        ok = weather.warm_cache(destinations.DESTINATIONS)
        print(f"기후 자료 {ok}/{len(destinations.DESTINATIONS)}곳 확보")
    elif command == "listen":
        print("텔레그램 명령 대기 중. 멈추려면 Ctrl+C")
        while True:
            notify.poll_updates(_handle, seconds=30)
    elif command == "status":
        print(config.summary())
        s = storage.stats()
        print(f"\n항공권 관측 {s['observations']:,}건 · 노선 {s['routes']}개")
        print(f"구독자 {len(storage.subscribers())}명")
    elif command == "test":
        # 버튼이 진짜 열리는지까지 확인한다. 예시는 도쿄 9/1~9/3.
        demo = notify.booking_sites("ICN", "NRT", "2026-09-01", "2026-09-03")
        if notify.send("연결 확인. 이 메시지가 보이면 준비 끝이다.\n\n"
                       "아래 버튼을 눌러 예매 사이트가 열리는지 봐라"
                       " (도쿄 9/1~9/3 예시).\n\n" + notify.HELP, buttons=demo):
            print("보냈다.")
        else:
            print("실패. TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 확인해라.")
            return 1
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n중단")
