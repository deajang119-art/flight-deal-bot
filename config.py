"""설정 로더. .env 파일과 환경변수를 읽는다. 외부 의존성 없음."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "deals.db"


def _load_env_file(path: Path) -> None:
    """python-dotenv 대체. KEY=VALUE 줄만 읽고 기존 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    """환경변수를 읽되 보이지 않는 찌꺼기를 떼어 낸다.

    깃허브 금고에 토큰을 넣을 때 앞에 BOM(\\ufeff)이 딸려 들어간 적이 있다.
    눈에 안 보이고 공백도 아니라서 strip() 으로 안 걸러지는데, 토큰은 한 글자만
    달라도 401 이 난다. 실제로 이것 때문에 항공권 조회가 전부 죽었다.
    """
    value = os.environ.get(key, default)
    return value.strip().lstrip("﻿").strip()


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(_get(key, str(default)))
    except ValueError:
        return default


# ── 텔레그램 ──────────────────────────────────────────────────────────
TELEGRAM_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# ── 항공권 가격 소스 ──────────────────────────────────────────────────
# travelpayouts: 월 단위 최저가를 한 번에 받아 스캔 비용이 낮다(권장, 기본 스캐너)
# amadeus: 실시간 조회. 후보를 최종 검증할 때만 쓴다(무료 티어 호출 수 제한)
TRAVELPAYOUTS_TOKEN = _get("TRAVELPAYOUTS_TOKEN")
AMADEUS_CLIENT_ID = _get("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = _get("AMADEUS_CLIENT_SECRET")
AMADEUS_HOST = _get("AMADEUS_HOST", "test.api.amadeus.com")  # 운영 전환 시 api.amadeus.com

# ── 검색 조건 ────────────────────────────────────────────────────────
ORIGIN = _get("ORIGIN", "ICN")             # 출발 공항
ORIGIN_CITY_KO = _get("ORIGIN_CITY_KO", "서울")
CURRENCY = _get("CURRENCY", "krw")

# 며칠 뒤부터 몇 달 앞까지 볼 것인가
SEARCH_START_DAYS = _get_int("SEARCH_START_DAYS", 14)   # 최소 리드타임
SEARCH_MONTHS = _get_int("SEARCH_MONTHS", 5)            # 앞으로 몇 개월치

# 여행 기간 규칙 (사용자 요구사항)
NEAR_MIN_DAYS = _get_int("NEAR_MIN_DAYS", 2)
NEAR_MAX_DAYS = _get_int("NEAR_MAX_DAYS", 4)
FAR_MIN_DAYS = _get_int("FAR_MIN_DAYS", 7)
FAR_MAX_DAYS = _get_int("FAR_MAX_DAYS", 14)

# 근거리/장거리 경계 (인천 기준 대권거리 km)
NEAR_FAR_KM = _get_int("NEAR_FAR_KM", 4500)

# ── 딜 판정 기준 ─────────────────────────────────────────────────────
# 평균가(중앙값) 대비 이만큼 이상 싸야 "딜"
DEAL_DROP_PCT = _get_float("DEAL_DROP_PCT", 25.0)
# 스카이스캐너 Drops 방식: 최근 7일 '최저가' 대비 하락폭.
# 중앙값 대비와는 잡는 게 다르다. 중앙값 대비는 '비싼 날짜들 사이의 싼 날'을,
# 이건 '노선 전체가 갑자기 떨어진 순간'을 잡는다. 둘 중 하나만 걸려도 딜로 본다.
WEEK_LOW_DROP_PCT = _get_float("WEEK_LOW_DROP_PCT", 20.0)
WEEK_LOW_DAYS = _get_int("WEEK_LOW_DAYS", 7)
# 대박(🔥) 기준
JACKPOT_DROP_PCT = _get_float("JACKPOT_DROP_PCT", 40.0)
# 날씨 점수 하한 (0~100)
MIN_WEATHER_SCORE = _get_float("MIN_WEATHER_SCORE", 60.0)
# 한 번 알림 보낸 (노선,날짜)는 이 기간 동안 다시 안 보냄
ALERT_COOLDOWN_HOURS = _get_int("ALERT_COOLDOWN_HOURS", 72)
# 한 번 스캔에 보낼 최대 알림 수
MAX_ALERTS_PER_SCAN = _get_int("MAX_ALERTS_PER_SCAN", 6)

# ── 여행사 자유여행 특가 ─────────────────────────────────────────────
# 여행사 상품은 '즉시할인 5%' 같은 상시 할인이 기본으로 붙어 있다.
# 그래서 항공권보다 문턱을 높게 잡아야 진짜 파격만 걸러진다.
PACKAGE_ENABLED = _get("PACKAGE_ENABLED", "1") not in ("0", "false", "no")
# 실측: 여행사 상시 할인은 딱 10%대라 정가 대비로는 파격이 안 잡힌다.
# 같은 목적지·같은 일수 또래 대비 25% 아래면 눈에 띄게 싼 축이다.
PACKAGE_DROP_PCT = _get_float("PACKAGE_DROP_PCT", 25.0)
PACKAGE_JACKPOT_PCT = _get_float("PACKAGE_JACKPOT_PCT", 40.0)
# 자유여행(에어텔)만 볼지, 패키지도 함께 볼지
PACKAGE_FIT_ONLY = _get("PACKAGE_FIT_ONLY", "1") not in ("0", "false", "no")
MAX_PACKAGE_ALERTS = _get_int("MAX_PACKAGE_ALERTS", 4)
# 같은 목적지 상품이 이만큼은 모여야 '또래 평균가'를 말할 수 있다
PACKAGE_MIN_PEERS = _get_int("PACKAGE_MIN_PEERS", 5)
# 여행사 서버를 두드리는 간격(초)
PACKAGE_DELAY = _get_float("PACKAGE_DELAY", 1.2)

# ── 스캔 시각 ────────────────────────────────────────────────────────
# 하루 정해진 시각에만 돈다. 비우면 SCAN_INTERVAL_HOURS 간격으로 돈다.
#
#   10:30 — 여행사가 특가를 올린 직후. 하나투어 타임세일이 월요일 오전 10시로
#           확인됐고, 여행사 상품 등록은 업무 시작 후 오전 중에 몰린다.
#   22:30 — 항공사는 영업시간이 없다(동적 가격이 24시간 돈다). 다만 '화요일
#           오후~수요일 새벽에 프로모션 요금이 걸린다'는 통설이 있어 그 직전을
#           잡는다. 밤 늦게라도 사람이 바로 예약할 수 있는 마지막 시간대다.
#
# 이 두 시각은 출발점일 뿐이다. `python main.py hours` 로 실제 우리 데이터에서
# 새 최저가가 몇 시에 나왔는지 보고 다시 정하는 게 맞다.
SCAN_TIMES = _get("SCAN_TIMES", "10:30,22:30")
SCAN_INTERVAL_HOURS = _get_float("SCAN_INTERVAL_HOURS", 6.0)


def scan_times() -> list[tuple[int, int]]:
    """'10:30,22:30' → [(10, 30), (22, 30)]. 형식이 틀린 건 버린다."""
    out: list[tuple[int, int]] = []
    for chunk in SCAN_TIMES.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        hh, _, mm = chunk.partition(":")
        try:
            hour, minute = int(hh), int(mm or 0)
        except ValueError:
            print(f"  [설정] 스캔 시각 '{chunk}' 을 못 읽어 건너뛴다")
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append((hour, minute))
    return sorted(set(out))

HTTP_TIMEOUT = _get_int("HTTP_TIMEOUT", 30)
USER_AGENT = "flight-deal-bot/1.0"


def missing_required() -> list[str]:
    """필수 설정 중 비어 있는 항목을 돌려준다."""
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TRAVELPAYOUTS_TOKEN and not (AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET):
        missing.append("TRAVELPAYOUTS_TOKEN 또는 AMADEUS_CLIENT_ID/SECRET")
    return missing


def summary() -> str:
    """현재 설정을 사람이 읽는 형태로."""
    lines = [
        f"출발지 {ORIGIN} · 통화 {CURRENCY.upper()}",
        f"검색 범위 {SEARCH_START_DAYS}일 뒤부터 {SEARCH_MONTHS}개월",
        f"근거리 {NEAR_MIN_DAYS}~{NEAR_MAX_DAYS}일 / 장거리 {FAR_MIN_DAYS}~{FAR_MAX_DAYS}일"
        f" (경계 {NEAR_FAR_KM:,}km)",
        f"항공권 딜 -{DEAL_DROP_PCT:.0f}% 이상 · 대박 -{JACKPOT_DROP_PCT:.0f}%",
        f"또는 최근 {WEEK_LOW_DAYS}일 최저가 대비 -{WEEK_LOW_DROP_PCT:.0f}% (Drops 방식)",
        f"날씨 하한 {MIN_WEATHER_SCORE:.0f}점",
        f"쿨다운 {ALERT_COOLDOWN_HOURS}시간 · 스캔당 최대 {MAX_ALERTS_PER_SCAN}건",
    ]
    if PACKAGE_ENABLED:
        lines.append(
            f"여행사 특가 -{PACKAGE_DROP_PCT:.0f}% 이상"
            f"{' · 자유여행만' if PACKAGE_FIT_ONLY else ' · 패키지 포함'}"
            f" · 최대 {MAX_PACKAGE_ALERTS}건"
        )
    else:
        lines.append("여행사 특가 꺼짐")
    times = scan_times()
    if times:
        lines.append("스캔 시각 " + ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
                     + f" (하루 {len(times)}번)")
    else:
        lines.append(f"스캔 주기 {SCAN_INTERVAL_HOURS:g}시간")
    return "\n".join(lines)
