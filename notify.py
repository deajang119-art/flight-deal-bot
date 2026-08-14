"""텔레그램 발송과 메시지 서식.

'어디서 사는지'까지 알려주는 게 목적이라, 항공권은 예매 사이트 네 곳 링크를
같이 붙인다. 아비아세일즈 링크는 그 가격을 찾은 바로 그 조합으로 들어간다.
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import time

import requests

import config
import storage
from deals import Deal
from packages import PackageDeal

API = "https://api.telegram.org/bot{token}/{method}"
WEEKDAY = ("월", "화", "수", "목", "금", "토", "일")


def _esc(text: str) -> str:
    return html_lib.escape(str(text), quote=False)


esc = _esc      # 다른 모듈에서 쓰는 이름


def _call(method: str, payload: dict) -> dict | None:
    if not config.TELEGRAM_TOKEN:
        print("  [텔레그램] 토큰이 없어 발송을 건너뛴다")
        return None
    try:
        resp = requests.post(
            API.format(token=config.TELEGRAM_TOKEN, method=method),
            json=payload, timeout=config.HTTP_TIMEOUT,
        )
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  [텔레그램] {method} 실패: {exc}")
        return None
    if not body.get("ok"):
        print(f"  [텔레그램] {method} 거부: {body.get('description')}")
        return None
    return body.get("result")


def send(text: str, chat_id: str | None = None) -> bool:
    targets = [chat_id] if chat_id else storage.subscribers()
    if not targets:
        print("  [텔레그램] 받을 사람이 없다. TELEGRAM_CHAT_ID를 채우거나 봇에게 /start 를 보내라")
        return False
    ok = False
    for target in targets:
        result = _call("sendMessage", {
            "chat_id": target,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        ok = ok or result is not None
        time.sleep(0.05)
    return ok


# ── 예매 사이트 링크 ─────────────────────────────────────────────────
def booking_links(origin: str, dest: str, depart: str, back: str,
                  direct_link: str = "") -> str:
    short_out = depart.replace("-", "")[2:]
    short_back = back.replace("-", "")[2:]
    sky = (f"https://www.skyscanner.co.kr/transport/flights/"
           f"{origin.lower()}/{dest.lower()}/{short_out}/{short_back}/")
    naver = (f"https://flight.naver.com/flights/international/"
             f"{origin}-{dest}-{depart.replace('-', '')}/"
             f"{dest}-{origin}-{back.replace('-', '')}?adult=1")
    google = ("https://www.google.com/travel/flights?hl=ko&q="
              f"Flights%20from%20{origin}%20to%20{dest}%20on%20{depart}%20returning%20{back}")

    parts = []
    if direct_link:
        parts.append(f'<a href="{_esc(direct_link)}">아비아세일즈</a>')
    parts.append(f'<a href="{sky}">스카이스캐너</a>')
    parts.append(f'<a href="{naver}">네이버항공권</a>')
    parts.append(f'<a href="{google}">구글플라이트</a>')
    return " · ".join(parts)


def _date_ko(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.month}/{d.day}({WEEKDAY[d.weekday()]})"


# ── 항공권 딜 ────────────────────────────────────────────────────────
def format_deal(deal: Deal) -> str:
    o = deal.offer
    head = "🔥 대박" if deal.is_jackpot else "✈️ 특가"
    tier = "짧게 다녀오기" if deal.dest.window[2] == "near" else "길게 다녀오기"

    route = f"{config.ORIGIN_CITY_KO} → {deal.dest.name_ko}"
    lines = [
        f"{head}  <b>{_esc(route)}</b>  "
        f"<b>{_esc(deal.basis)} 대비 -{deal.headline_pct:.0f}%</b>",
        "",
        f"<b>{o.price:,}원</b>  (평소 {deal.baseline:,}원 · {deal.saved:,}원 덜 냄)",
        f"{_date_ko(o.depart_date)} → {_date_ko(o.return_date)} · {o.days}일 ({tier})",
    ]

    detail = []
    if o.airline:
        detail.append(_esc(o.airline))
    detail.append("직항" if o.transfers == 0 else f"경유 {o.transfers}회")
    lines.append(" · ".join(detail))

    lines.append(f"날씨 {deal.weather_score:.0f}점 · {_esc(deal.weather_summary)}")

    extra = [n for n in deal.notes if n != "직항"]
    if extra:
        lines.append("· " + " · ".join(_esc(n) for n in extra))

    lines.append("")
    lines.append(booking_links(o.origin, o.destination, o.depart_date,
                               o.return_date, o.link))
    return "\n".join(lines)


# ── 여행사 자유여행 특가 ─────────────────────────────────────────────
def format_package(deal: PackageDeal) -> str:
    p = deal.pkg
    head = "🔥 여행사 대박" if deal.is_jackpot else "🏝 여행사 특가"
    lines = [
        f"{head}  <b>{_esc(p.source_ko)}</b>  <b>-{deal.drop_pct:.0f}%</b>",
        "",
        f"<b>{_esc(p.title)}</b>",
        f"<b>{p.price:,}원</b>  ({_esc(deal.basis)} {deal.baseline:,}원 · "
        f"{deal.saved:,}원 덜 냄)",
    ]
    if deal.notes:
        lines.append("· " + " · ".join(_esc(n) for n in deal.notes))
    lines.append("")
    lines.append(f'<a href="{_esc(p.url)}">상품 보러 가기</a>')
    return "\n".join(lines)


# ── 묶음 발송 ────────────────────────────────────────────────────────
def send_deals(flight_deals: list[Deal], package_deals: list[PackageDeal]) -> int:
    sent = 0
    for d in flight_deals:
        if send(format_deal(d)):
            storage.mark_alerted(d.key, d.offer.price)
            sent += 1
        time.sleep(0.4)
    for d in package_deals:
        if send(format_package(d)):
            storage.mark_alerted(d.key, d.pkg.price)
            sent += 1
        time.sleep(0.4)
    return sent


def send_health_warning(broken: list[str]) -> None:
    if not broken:
        return
    send("⚠️ <b>수집 이상</b>\n\n"
         f"{_esc(', '.join(broken))} 에서 상품을 한 건도 못 읽었다.\n"
         "사이트 구조가 바뀌었을 가능성이 높다 — 파서 점검이 필요하다.")


# ── 수신(구독 등록) ──────────────────────────────────────────────────
HELP = (
    "<b>항공권·자유여행 특가 알리미</b>\n\n"
    "/start 알림 받기\n"
    "/stop 알림 끄기\n"
    "/status 현재 설정과 수집 현황\n"
    "/now 지금 바로 한 번 훑기"
)


def poll_updates(handler, seconds: int = 30) -> None:
    """봇에게 온 명령을 받아 처리한다. handler(chat_id, command) 호출."""
    offset = int(storage.get_meta("tg_offset", "0") or 0)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = _call("getUpdates", {"offset": offset + 1, "timeout": 10})
        if result is None:
            return
        for update in result:
            offset = max(offset, update.get("update_id", 0))
            message = update.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id") or "")
            text = (message.get("text") or "").strip().split()[0:1]
            if chat_id and text:
                handler(chat_id, text[0].lower())
        storage.set_meta("tg_offset", str(offset))
