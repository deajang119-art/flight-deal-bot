"""여행사 자유여행·특가 상품 수집.

여행사는 공개 API를 주지 않는다. 그래서 상품 목록 페이지에서 직접 읽는다.
사이트 개편이 잦으므로 소스별로 파서를 분리하고, 수집 0건이면 조용히 넘어가지
않고 '구조 변경 의심'으로 보고한다(health 참고).

'파격할인'은 세 가지로 판정한다.
  1. 정가 대비 할인율 (웹투어처럼 취소선 정가를 같이 주는 곳)
  2. 우리가 관측해 온 그 상품의 평소 가격 대비 하락
  3. 같은 목적지 또래 상품들의 중앙값 대비 하락  ← 첫 실행부터 작동
셋 중 가장 큰 값을 그 상품의 할인율로 본다.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

import config
import storage
from destinations import DESTINATIONS

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 자유여행(에어텔)로 볼 제목 키워드
FIT_WORDS = ("자유여행", "에어텔", "자유일정", "세미패키지", "반자유", "FIT", "허니문자유")

# 항공이 빠진 숙박 전용 상품. 에어텔과 같이 줄 세우면 무조건 싸 보여서 오탐이 된다.
STAY_ONLY_WORDS = ("룸only", "룸 only", "룸온리", "호텔only", "호텔 only",
                   "숙박만", "객실만", "호텔단품", "항공불포함", "항공 불포함",
                   "항공미포함", "티켓만", "입장권")

# 목적지 별칭. 제목에 이 말이 있으면 그 도시로 본다.
ALIASES: dict[str, str] = {
    "다낭": "DAD", "나트랑": "CXR", "냐짱": "CXR", "푸꾸옥": "PQC",
    "하노이": "HAN", "호치민": "SGN", "호찌민": "SGN", "달랏": "CXR",
    "방콕": "BKK", "치앙마이": "CNX", "푸켓": "HKT", "파타야": "BKK",
    "세부": "CEB", "보라카이": "MNL", "마닐라": "MNL", "클락": "MNL",
    "코타키나발루": "KUL", "쿠알라룸푸르": "KUL", "싱가포르": "SIN",
    "발리": "DPS", "자카르타": "DPS", "빈탄": "SIN",
    "괌": "GUM", "사이판": "SPN",
    "후쿠오카": "FUK", "오사카": "KIX", "교토": "KIX", "도쿄": "NRT",
    "삿포로": "CTS", "오키나와": "OKA", "나고야": "NGO", "가고시마": "KOJ",
    "히로시마": "HIJ", "센다이": "SDJ", "벳푸": "FUK", "유후인": "FUK",
    "타이베이": "TPE", "타이페이": "TPE", "가오슝": "KHH", "대만": "TPE",
    "홍콩": "HKG", "마카오": "MFM", "상하이": "PVG", "베이징": "PEK",
    "장가계": "CAN", "시안": "XIY", "칭다오": "PEK",
    "울란바토르": "UBN", "몽골": "UBN", "블라디보스토크": "VVO",
    "씨엠립": "SAI", "앙코르": "SAI", "프놈펜": "PNH", "라오스": "VTE",
    "파리": "CDG", "런던": "LHR", "로마": "FCO", "바르셀로나": "BCN",
    "마드리드": "MAD", "프라하": "PRG", "비엔나": "VIE", "빈": "VIE",
    "뮌헨": "MUC", "암스테르담": "AMS", "취리히": "ZRH", "스위스": "ZRH",
    "리스본": "LIS", "포르투갈": "LIS", "아테네": "ATH", "그리스": "ATH",
    "이스탄불": "IST", "튀르키예": "IST", "터키": "IST",
    "부다페스트": "BUD", "코펜하겐": "CPH", "헬싱키": "HEL", "오슬로": "OSL",
    "로스앤젤레스": "LAX", "LA": "LAX", "샌프란시스코": "SFO",
    "시애틀": "SEA", "뉴욕": "JFK", "보스턴": "BOS", "시카고": "ORD",
    "라스베이거스": "LAS", "하와이": "HNL", "호놀룰루": "HNL",
    "밴쿠버": "YVR", "토론토": "YYZ", "칸쿤": "CUN", "멕시코": "MEX",
    "시드니": "SYD", "멜버른": "MEL", "브리즈번": "BNE", "케언스": "CNS",
    "오클랜드": "AKL", "뉴질랜드": "AKL", "호주": "SYD",
    "두바이": "DXB", "도하": "DOH", "아부다비": "AUH",
    "델리": "DEL", "인도": "DEL", "스리랑카": "CMB", "몰디브": "MLE",
    "네팔": "KTM", "카트만두": "KTM",
}
for _d in DESTINATIONS:
    ALIASES.setdefault(_d.name_ko, _d.iata)

_IATA_TO_LABEL = {d.iata: d.label for d in DESTINATIONS}

_last_fetch = 0.0


@dataclass
class Package:
    source: str
    source_ko: str
    code: str
    title: str
    price: int
    url: str
    list_price: int | None = None
    dest_key: str = ""
    is_fit: bool = False
    stay_only: bool = False
    days: int | None = None

    @property
    def dest_label(self) -> str:
        return _IATA_TO_LABEL.get(self.dest_key, "")

    @property
    def peer_key(self) -> str:
        """또래 비교 묶음. 목적지가 같아도 3일과 7일을 같이 놓으면 안 된다."""
        if not self.dest_key:
            return ""
        return f"{self.dest_key}|{_duration_bucket(self.days)}"

    def as_row(self) -> dict:
        return {
            "source": self.source, "code": self.code, "title": self.title,
            "dest_key": self.peer_key, "price": self.price,
            "list_price": self.list_price, "is_fit": self.is_fit, "url": self.url,
        }


@dataclass
class PackageDeal:
    pkg: Package
    baseline: int
    drop_pct: float
    basis: str                       # 무엇과 비교했는지
    samples: int
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"PKG|{self.pkg.source}|{self.pkg.code}"

    @property
    def is_jackpot(self) -> bool:
        return self.drop_pct >= config.PACKAGE_JACKPOT_PCT

    @property
    def saved(self) -> int:
        return int(self.baseline - self.pkg.price)


# ── 공통 유틸 ────────────────────────────────────────────────────────
def _fetch(url: str) -> str | None:
    global _last_fetch
    gap = time.monotonic() - _last_fetch
    if gap < config.PACKAGE_DELAY:
        time.sleep(config.PACKAGE_DELAY - gap)
    _last_fetch = time.monotonic()
    try:
        resp = requests.get(
            url, timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"},
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text
    except requests.RequestException as exc:
        print(f"  [여행사] {url} 실패: {exc}")
        return None


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def _dest_of(title: str) -> str:
    """제목에서 목적지를 찾는다. 긴 이름부터 맞춰 '대만'이 '대만족'을 먹지 않게."""
    for word in sorted(ALIASES, key=len, reverse=True):
        if word in title:
            return ALIASES[word]
    return ""


def _is_fit(title: str) -> bool:
    upper = title.upper()
    return any(w.upper() in upper for w in FIT_WORDS)


def _is_stay_only(title: str) -> bool:
    lowered = title.lower().replace(" ", "")
    return any(w.lower().replace(" ", "") in lowered for w in STAY_ONLY_WORDS)


_NIGHTS = re.compile(r"(\d+)\s*박")
_RANGE_DAYS = re.compile(r"(\d+)\s*/\s*(\d+)\s*일")
_DAYS = re.compile(r"(\d+)\s*일")


def _duration_of(title: str) -> int | None:
    """제목에서 여행 일수를 뽑는다. '3박5일'>'4/5일'>'5일' 순으로 믿는다."""
    m = _NIGHTS.search(title)
    if m:
        return int(m.group(1)) + 1
    m = _RANGE_DAYS.search(title)
    if m:
        return max(int(m.group(1)), int(m.group(2)))
    found = [int(x) for x in _DAYS.findall(title) if 2 <= int(x) <= 20]
    return max(found) if found else None


def _duration_bucket(days: int | None) -> str:
    if days is None:
        return "?"
    if days <= 3:
        return "S"      # 짧게
    if days <= 5:
        return "M"      # 주말 끼고
    if days <= 7:
        return "L"
    return "X"


def _make(source: str, source_ko: str, code: str, title: str,
          price: int, url: str, list_price: int | None = None) -> Package | None:
    title = _clean(title)
    if not title or price <= 0:
        return None
    if list_price and list_price <= price:
        list_price = None
    return Package(
        source=source, source_ko=source_ko, code=code, title=title,
        price=price, url=url, list_price=list_price,
        dest_key=_dest_of(title), is_fit=_is_fit(title),
        stay_only=_is_stay_only(title), days=_duration_of(title),
    )


# ── 소스 1: 웹투어 (정가/할인가를 함께 준다) ─────────────────────────
WEBTOUR_REGIONS = {
    "M1": "괌/사이판", "M2": "동남아", "M3": "유럽/아프리카/중동",
    "M4": "일본", "M5": "미주/하와이/캐나다", "M6": "중국/몽골",
    "M8": "호주/뉴질랜드", "M9": "대만/홍콩/마카오",
}
_WT_ITEM = re.compile(
    r"goEvtGdsDetail\(\s*'(?P<gubun>[A-Z]+)'\s*,\s*'G'\s*,\s*'(?P<code>[A-Z0-9]+)'\s*\)"
    r"[\s\S]{0,1200}?<span class=\"tit\">(?P<title>[\s\S]*?)</span>"
    r"[\s\S]{0,800}?<span class=\"price\">(?P<price>[\s\S]*?)</span>\s*</span>"
)
_WT_DC = re.compile(r"<span class=\"dc\">\s*([\d,]+)\s*원\s*</span>")
_WT_NUM = re.compile(r"([\d,]+)\s*원")


def parse_webtour(page: str) -> list[Package]:
    out: list[Package] = []
    for m in _WT_ITEM.finditer(page):
        block = m.group("price")
        list_price = _to_int(_WT_DC.search(block).group(1)) if _WT_DC.search(block) else None
        numbers = [_to_int(n) for n in _WT_NUM.findall(block)]
        numbers = [n for n in numbers if n]
        if not numbers:
            continue
        price = numbers[-1]          # 마지막이 실제 판매가
        gubun = m.group("gubun").lower()
        code = m.group("code")
        url = f"https://m.webtour.com/{gubun}/{gubun}_detail.asp?GdsCode={code}"
        pkg = _make("webtour", "웹투어", code, m.group("title"), price, url, list_price)
        if pkg:
            out.append(pkg)
    return out


def fetch_webtour() -> list[Package]:
    pages = ["https://m.webtour.com/AP/index.asp"] + [
        f"https://m.webtour.com/AP/ap_sub.asp?araC1={code}" for code in WEBTOUR_REGIONS
    ]
    found: list[Package] = []
    for url in pages:
        page = _fetch(url)
        if page:
            found.extend(parse_webtour(page))
    return found


# ── 소스 2: 모두투어 (Next.js 내장 JSON) ─────────────────────────────
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>')


def _walk_products(node, out: list[dict]) -> None:
    if isinstance(node, dict):
        name = node.get("productsName") or node.get("masterProductName")
        if name and ("price" in node or "minPrice" in node):
            out.append(node)
        for value in node.values():
            _walk_products(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_products(value, out)


def parse_modetour(page: str) -> list[Package]:
    m = _NEXT_DATA.search(page)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    raw: list[dict] = []
    _walk_products(data.get("props", {}), raw)

    out: list[Package] = []
    seen: set[str] = set()
    for item in raw:
        price = item.get("price")
        if isinstance(price, dict):
            price = price.get("minPrice") or price.get("amount") or price.get("price")
        price = _to_int(price)
        if not price:
            price = _to_int(item.get("minPrice"))
        if not price:
            continue
        code = str(item.get("productsCode") or item.get("masterCode") or "").strip()
        title = str(item.get("productsName") or item.get("masterProductName") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        url = str(item.get("asisurl") or "")
        if not url.startswith("http"):
            url = f"https://www.modetour.com/package/detail?masterCode={code}"
        pkg = _make("modetour", "모두투어", code, title, price, url)
        if pkg:
            tags = item.get("tag") or item.get("tags") or []
            if isinstance(tags, list) and any("자유" in str(t) or "에어텔" in str(t) for t in tags):
                pkg.is_fit = True
            out.append(pkg)
    return out


def fetch_modetour() -> list[Package]:
    found: list[Package] = []
    for url in ("https://www.modetour.com/",
                "https://www.modetour.com/package/overseas"):
        page = _fetch(url)
        if page:
            found.extend(parse_modetour(page))
    return found


# ── 소스 3: 온라인투어 ───────────────────────────────────────────────
_OT_ITEM = re.compile(
    r'<div class="prd_unit_itm"><a href="(?P<url>[^"]+)"[\s\S]*?'
    r'<span class="prd_unit_name[^"]*">(?P<title>[\s\S]*?)</span>'
    r'\s*<span class="prd_unit_price">(?P<price>[\d,]+)\s*원'
)


def parse_onlinetour(page: str) -> list[Package]:
    out: list[Package] = []
    seen: set[str] = set()
    for m in _OT_ITEM.finditer(page):
        href = html_lib.unescape(m.group("url"))
        price = _to_int(m.group("price"))
        if not price:
            continue
        good = re.search(r"goodCode=([A-Za-z0-9]+)", href)
        code = good.group(1) if good else href[-24:]
        if code in seen:
            continue
        seen.add(code)
        url = href if href.startswith("http") else "https://www.onlinetour.co.kr" + href
        pkg = _make("onlinetour", "온라인투어", code, m.group("title"), price, url)
        if pkg:
            out.append(pkg)
    return out


def fetch_onlinetour() -> list[Package]:
    page = _fetch("https://www.onlinetour.co.kr/")
    return parse_onlinetour(page) if page else []


# ── 소스 등록 ────────────────────────────────────────────────────────
SOURCES: dict[str, Callable[[], list[Package]]] = {
    "웹투어": fetch_webtour,
    "모두투어": fetch_modetour,
    "온라인투어": fetch_onlinetour,
}


def collect() -> tuple[list[Package], dict[str, int]]:
    """모든 여행사에서 상품을 긁어온다. (상품목록, 소스별 건수)"""
    all_pkgs: list[Package] = []
    health: dict[str, int] = {}
    for name, fetcher in SOURCES.items():
        try:
            got = fetcher()
        except Exception as exc:                      # 한 곳이 깨져도 나머지는 살린다
            print(f"  [여행사] {name} 파서 오류: {exc}")
            got = []
        health[name] = len(got)
        all_pkgs.extend(got)
        print(f"  [여행사] {name}: {len(got)}건")
    return all_pkgs, health


def broken_sources(health: dict[str, int]) -> list[str]:
    """0건인 소스는 사이트 구조가 바뀌었을 가능성이 높다."""
    return [name for name, count in health.items() if count == 0]


def dedupe(pkgs: list[Package]) -> list[Package]:
    """같은 상품코드가 출발일·노출 위치에 따라 여러 가격으로 나온다.

    그대로 두면 '평소가' 이력이 한 시점의 편차로 채워져 비교가 망가진다.
    한 번의 스캔에서는 상품마다 가장 싼 것 하나만 남긴다.
    """
    best: dict[tuple[str, str], Package] = {}
    for p in pkgs:
        k = (p.source, p.code)
        if k not in best or p.price < best[k].price:
            best[k] = p
    return list(best.values())


# ── 딜 판정 ──────────────────────────────────────────────────────────
def evaluate(pkgs: list[Package]) -> list[PackageDeal]:
    """기준을 넘은 특가만. 관측 기록도 여기서 남긴다."""
    pkgs = dedupe(pkgs)
    storage.save_packages([p.as_row() for p in pkgs])
    return _score(pkgs, config.PACKAGE_DROP_PCT)


def evaluate_all(pkgs: list[Package]) -> list[PackageDeal]:
    """기준 미달까지 전부. 수집이 죽었는지 눈으로 확인할 때 쓴다(기록 안 남김)."""
    return _score(dedupe(pkgs), -1000.0)


def _score(pkgs: list[Package], min_pct: float) -> list[PackageDeal]:
    # 이번 스캔 안에서 또래 가격을 먼저 모은다.
    # 숙박 전용 상품은 항공이 빠져 있어 또래 평균을 끌어내리므로 표본에서 뺀다.
    peers_now: dict[str, list[int]] = {}
    for p in pkgs:
        if p.peer_key and not p.stay_only:
            peers_now.setdefault(p.peer_key, []).append(p.price)

    deals: list[PackageDeal] = []
    for p in pkgs:
        if config.PACKAGE_FIT_ONLY and not p.is_fit:
            continue
        if p.stay_only:
            continue

        options: list[tuple[float, int, str, int]] = []   # (할인율, 기준가, 근거, 표본수)

        # 1. 정가 대비
        if p.list_price:
            pct = (p.list_price - p.price) / p.list_price * 100.0
            options.append((pct, p.list_price, "정가", 1))

        # 2. 이 상품의 평소 가격 대비
        history = storage.package_history(p.source, p.code)
        if len(history) >= 3:
            base = storage.median(history)
            if base and base > 0:
                options.append(((base - p.price) / base * 100.0, int(base), "평소가", len(history)))

        # 3. 같은 목적지·비슷한 일수 또래 상품 대비
        peers = peers_now.get(p.peer_key, []) + storage.package_peer_prices(p.peer_key)
        if len(peers) >= config.PACKAGE_MIN_PEERS:
            base = storage.median(peers)
            if base and base > 0:
                label = f"{p.dest_label or '같은 목적지'} {p.days}일 평균" if p.days else "같은 목적지 평균"
                options.append(((base - p.price) / base * 100.0, int(base), label, len(peers)))

        if not options:
            continue
        pct, base, basis, samples = max(options, key=lambda x: x[0])
        if pct < min_pct:
            continue

        deal = PackageDeal(pkg=p, baseline=base, drop_pct=round(pct, 1),
                           basis=basis, samples=samples)
        if p.list_price:
            deal.notes.append(f"정가 {p.list_price:,}원")
        if p.days:
            deal.notes.append(f"{p.days}일")
        deals.append(deal)

    deals.sort(key=lambda d: d.drop_pct, reverse=True)
    return deals


def filter_new(deals: list[PackageDeal]) -> list[PackageDeal]:
    fresh = [
        d for d in deals
        if not storage.recently_alerted(d.key, config.ALERT_COOLDOWN_HOURS, d.pkg.price)
    ]
    return fresh[: config.MAX_PACKAGE_ALERTS]
