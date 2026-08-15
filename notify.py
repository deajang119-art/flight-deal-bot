"""텔레그램 발송과 메시지 서식.

'어디서 사는지'까지 알려주는 게 목적이라, 항공권은 예매 사이트 네 곳으로
바로 가는 길을 같이 보낸다. 아비아세일즈 링크는 그 가격을 찾은 바로 그
조합(노선·날짜)으로 들어간다.

길은 두 겹으로 깐다.
  ① 말풍선 아래 **버튼**(텔레그램 inline keyboard) — 손가락으로 누르기 쉽다.
  ② 본문 맨 아래 **글자 링크** — 버튼이 안 보이는 데(웹 미리보기, 메시지 전달
     후 일부 클라이언트)서도 주소가 남는다.
둘 다 같은 주소다.
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


def send(text: str, chat_id: str | None = None,
         buttons: list[tuple[str, str]] | None = None) -> bool:
    """메시지를 보낸다. buttons 는 (버튼 글자, 주소) 목록. 두 개씩 한 줄에 깐다."""
    targets = [chat_id] if chat_id else storage.subscribers()
    if not targets:
        print("  [텔레그램] 받을 사람이 없다. TELEGRAM_CHAT_ID를 채우거나 봇에게 /start 를 보내라")
        return False
    payload_base = {
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    markup = keyboard(buttons)
    if markup:
        payload_base["reply_markup"] = markup
    ok = False
    for target in targets:
        result = _call("sendMessage", dict(payload_base, chat_id=target))
        if result is None and markup:
            # 버튼 때문에 거부당했을 수 있다(주소가 이상하면 텔레그램이 통째로 막는다).
            # 알림을 통째로 날리느니 버튼을 떼고라도 보낸다. 글자 링크는 본문에 남아 있다.
            print("  [텔레그램] 버튼 없이 다시 보낸다")
            result = _call("sendMessage", dict(payload_base, chat_id=target,
                                               reply_markup=None))
        ok = ok or result is not None
        time.sleep(0.05)
    return ok


def keyboard(buttons: list[tuple[str, str]] | None,
             per_row: int = 2) -> dict | None:
    """(글자, 주소) 목록을 텔레그램 버튼판으로. 주소가 http 로 시작하는 것만 남긴다."""
    valid = [(label, url) for label, url in (buttons or [])
             if url and url.startswith("http")]
    if not valid:
        return None
    rows = [valid[i:i + per_row] for i in range(0, len(valid), per_row)]
    return {"inline_keyboard": [[{"text": label, "url": url} for label, url in row]
                                for row in rows]}


# ── 예매 사이트 링크 ─────────────────────────────────────────────────
def _add_query(url: str, extra: str) -> str:
    """주소에 조건을 덧붙인다. 이미 ? 가 있으면 & 로 잇는다."""
    if not url:
        return url
    return url + ("&" if "?" in url else "?") + extra


def booking_sites(origin: str, dest: str, depart: str, back: str,
                  direct_link: str = "", source: str = "") -> list[tuple[str, str]]:
    """이 노선·이 날짜로 바로 열리는 예매 사이트 (이름, 주소) 목록.

    순서는 '바로 그 값이 나올 확률' 순이다.
      아비아세일즈 = 우리가 그 가격을 찾은 바로 그 검색 결과(가장 정확)
      네이버항공권 = 국내에서 결제까지 가장 편함
      스카이스캐너 = 폭이 넓음(사람이 누르면 정상, 자동 조회만 captcha가 뜬다)
      구글플라이트 = 날짜를 앞뒤로 흔들어 볼 때
    아비아세일즈는 기본이 달러라 원화로 열리게 currency=krw 를 붙인다
    (실측 확인: data-currency 가 usd → krw 로 바뀐다. 화면 말은 영어 그대로).
    """
    short_out = depart.replace("-", "")[2:]
    short_back = back.replace("-", "")[2:]
    sky = (f"https://www.skyscanner.co.kr/transport/flights/"
           f"{origin.lower()}/{dest.lower()}/{short_out}/{short_back}/")
    naver = (f"https://flight.naver.com/flights/international/"
             f"{origin}-{dest}-{depart.replace('-', '')}/"
             f"{dest}-{origin}-{back.replace('-', '')}?adult=1")
    google = ("https://www.google.com/travel/flights?hl=ko&q="
              f"Flights%20from%20{origin}%20to%20{dest}%20on%20{depart}%20returning%20{back}")

    sites: list[tuple[str, str]] = []
    if direct_link and source == "naver":
        # 네이버에서 찾은 값이면 그 링크가 곧 네이버 화면이다. 두 번 깔지 않는다.
        sites.append(("🇰🇷 네이버(이 일정)", direct_link))
    elif direct_link:
        sites.append(("🎫 아비아세일즈(이 가격)", _add_query(direct_link, "currency=krw")))
        sites.append(("🇰🇷 네이버항공권", naver))
    else:
        sites.append(("🇰🇷 네이버항공권", naver))
    sites.append(("🌐 스카이스캐너", sky))
    sites.append(("🔎 구글플라이트", google))
    return sites


def booking_links(origin: str, dest: str, depart: str, back: str,
                  direct_link: str = "", source: str = "") -> str:
    """같은 주소를 본문 글자 링크 한 줄로."""
    return " · ".join(
        f'<a href="{_esc(url)}">{_esc(label.split(" ", 1)[-1])}</a>'
        for label, url in booking_sites(origin, dest, depart, back, direct_link, source)
    )


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
    lo, hi, kind = deal.dest.window
    if lo <= o.days <= hi:
        tier = "짧게 다녀오기" if kind == "near" else "길게 다녀오기"
    else:
        # 네이버 경로는 거리별 일수 규칙을 안 걸어서 이런 일정이 올라온다
        tier = "평소 규칙보다 긴 일정" if o.days > hi else "평소 규칙보다 짧은 일정"

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
    lines.append("👇 <b>예매하러 가기</b> — 아래 버튼을 누르면 이 날짜로 바로 열린다")
    lines.append(booking_links(o.origin, o.destination, o.depart_date,
                               o.return_date, o.link, o.source))
    return "\n".join(lines)


def deal_buttons(deal: Deal) -> list[tuple[str, str]]:
    o = deal.offer
    return booking_sites(o.origin, o.destination, o.depart_date,
                         o.return_date, o.link, o.source)


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
    lines.append("👇 <b>예약하러 가기</b> — 아래 버튼이 이 상품 화면이다")
    lines.append(" · ".join(
        f'<a href="{_esc(url)}">{_esc(label.split(" ", 1)[-1])}</a>'
        for label, url in package_buttons(deal)
    ))
    return "\n".join(lines)


# 여행사 홈. 상품이 내려갔을 때(특가는 금방 팔린다) 같은 상품을 찾아볼 자리다.
AGENCY_HOME = {
    "webtour": "https://m.webtour.com/AP/index.asp",
    "modetour": "https://www.modetour.com/package/overseas",
    "onlinetour": "https://www.onlinetour.co.kr/",
}


def package_buttons(deal: PackageDeal) -> list[tuple[str, str]]:
    p = deal.pkg
    sites: list[tuple[str, str]] = []
    if p.url:
        sites.append((f"🏝 {p.source_ko} 이 상품", p.url))
    home = AGENCY_HOME.get(p.source)
    if home:
        sites.append((f"🏠 {p.source_ko} 특가 목록", home))
    return sites


# ── 묶음 발송 ────────────────────────────────────────────────────────
def send_deals(flight_deals: list[Deal], package_deals: list[PackageDeal]) -> int:
    sent = 0
    for d in flight_deals:
        if send(format_deal(d), buttons=deal_buttons(d)):
            storage.mark_alerted(d.key, d.offer.price)
            sent += 1
        time.sleep(0.4)
    for d in package_deals:
        if send(format_package(d), buttons=package_buttons(d)):
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
