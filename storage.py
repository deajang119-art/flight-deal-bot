"""SQLite 저장소. 가격 관측 이력, 기후 캐시, 발송 이력, 구독자."""
from __future__ import annotations

import json
import sqlite3
import statistics
import time
from contextlib import contextmanager
from typing import Iterable, Iterator

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_obs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at  INTEGER NOT NULL,        -- unix epoch
    origin       TEXT    NOT NULL,
    destination  TEXT    NOT NULL,
    depart_date  TEXT    NOT NULL,        -- YYYY-MM-DD
    return_date  TEXT    NOT NULL,
    days         INTEGER NOT NULL,
    price        INTEGER NOT NULL,        -- 통화 단위 정수(기본 KRW)
    airline      TEXT,
    transfers    INTEGER,
    source       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_route      ON price_obs(origin, destination, observed_at);
CREATE INDEX IF NOT EXISTS idx_obs_route_date ON price_obs(origin, destination, depart_date, return_date);

CREATE TABLE IF NOT EXISTS package_obs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at  INTEGER NOT NULL,
    source       TEXT    NOT NULL,        -- 여행사
    code         TEXT    NOT NULL,        -- 여행사 내부 상품코드
    title        TEXT    NOT NULL,
    dest_key     TEXT    NOT NULL,        -- 제목에서 뽑은 목적지(없으면 '')
    price        INTEGER NOT NULL,
    list_price   INTEGER,                 -- 정가(취소선). 없으면 NULL
    is_fit       INTEGER NOT NULL DEFAULT 0,
    url          TEXT
);
CREATE INDEX IF NOT EXISTS idx_pkg_code ON package_obs(source, code, observed_at);
CREATE INDEX IF NOT EXISTS idx_pkg_dest ON package_obs(dest_key, observed_at);

CREATE TABLE IF NOT EXISTS climate_cache (
    iata        TEXT PRIMARY KEY,
    fetched_at  INTEGER NOT NULL,
    payload     TEXT    NOT NULL          -- month -> stats JSON
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    key        TEXT PRIMARY KEY,          -- dest|depart|return
    sent_at    INTEGER NOT NULL,
    price      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subscribers (
    chat_id    TEXT PRIMARY KEY,
    added_at   INTEGER NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


# ── 가격 관측 ────────────────────────────────────────────────────────
def save_observations(rows: Iterable[dict]) -> int:
    payload = [
        (
            int(r.get("observed_at") or time.time()),
            r["origin"], r["destination"], r["depart_date"], r["return_date"],
            int(r["days"]), int(r["price"]),
            r.get("airline"), r.get("transfers"), r.get("source", "unknown"),
        )
        for r in rows
    ]
    if not payload:
        return 0
    with db() as conn:
        conn.executemany(
            "INSERT INTO price_obs (observed_at, origin, destination, depart_date,"
            " return_date, days, price, airline, transfers, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
    return len(payload)


def historical_prices(origin: str, destination: str, days_back: int = 90) -> list[int]:
    """최근 N일 사이에 관측된 그 노선의 모든 가격."""
    since = int(time.time()) - days_back * 86400
    with db() as conn:
        rows = conn.execute(
            "SELECT price FROM price_obs WHERE origin=? AND destination=? AND observed_at>=?",
            (origin, destination, since),
        ).fetchall()
    return [r["price"] for r in rows]


def week_low(origin: str, destination: str, days: int = 7) -> tuple[int | None, int]:
    """최근 N일 그 노선의 최저가와 관측 수.

    스카이스캐너 Drops가 쓰는 기준선이다. 중앙값과 달리 '이미 싼 값'이 기준이라
    같은 퍼센트라도 훨씬 넘기 어렵다. 그만큼 걸리면 진짜다.
    """
    since = int(time.time()) - days * 86400
    with db() as conn:
        row = conn.execute(
            "SELECT MIN(price) lo, COUNT(*) n FROM price_obs"
            " WHERE origin=? AND destination=? AND observed_at>=?",
            (origin, destination, since),
        ).fetchone()
    return (row["lo"], row["n"]) if row else (None, 0)


def new_low_hours(days_back: int = 60) -> dict[int, int]:
    """새 최저가가 몇 시에 관측됐는지 세어 돌려준다.

    스캔 시각을 감으로 정하지 않으려고 만든 것이다. 노선별로 시간순으로 훑으며
    직전까지의 최저가를 깬 순간만 골라 그 시각(로컬 시)을 센다.
    """
    since = int(time.time()) - days_back * 86400
    with db() as conn:
        rows = conn.execute(
            "SELECT origin, destination, observed_at, price FROM price_obs"
            " WHERE observed_at>=? ORDER BY origin, destination, observed_at",
            (since,),
        ).fetchall()

    hours: dict[int, int] = {}
    current_route = None
    best = None
    for r in rows:
        route = (r["origin"], r["destination"])
        if route != current_route:
            current_route, best = route, None
        if best is None or r["price"] < best:
            if best is not None:          # 첫 관측은 '하락'이 아니다
                hour = time.localtime(r["observed_at"]).tm_hour
                hours[hour] = hours.get(hour, 0) + 1
            best = r["price"]
    return hours


def median(values: list[int]) -> float | None:
    return statistics.median(values) if values else None


def percentile(values: list[int], pct: float) -> float | None:
    """선형 보간 없는 단순 백분위(작은 표본에서 과민 반응을 피하려 보수적으로 올림)."""
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return float(ordered[idx])


def purge_old(days_keep: int = 365) -> int:
    cutoff = int(time.time()) - days_keep * 86400
    with db() as conn:
        cur = conn.execute("DELETE FROM price_obs WHERE observed_at < ?", (cutoff,))
        return cur.rowcount


# ── 여행사 상품 관측 ─────────────────────────────────────────────────
def save_packages(rows: Iterable[dict]) -> int:
    payload = [
        (
            int(r.get("observed_at") or time.time()),
            r["source"], r["code"], r["title"], r.get("dest_key", ""),
            int(r["price"]),
            int(r["list_price"]) if r.get("list_price") else None,
            1 if r.get("is_fit") else 0,
            r.get("url", ""),
        )
        for r in rows
    ]
    if not payload:
        return 0
    with db() as conn:
        conn.executemany(
            "INSERT INTO package_obs (observed_at, source, code, title, dest_key,"
            " price, list_price, is_fit, url) VALUES (?,?,?,?,?,?,?,?,?)",
            payload,
        )
    return len(payload)


def package_history(source: str, code: str, days_back: int = 120) -> list[int]:
    """그 상품을 지금까지 관측한 가격들."""
    since = int(time.time()) - days_back * 86400
    with db() as conn:
        rows = conn.execute(
            "SELECT price FROM package_obs WHERE source=? AND code=? AND observed_at>=?",
            (source, code, since),
        ).fetchall()
    return [r["price"] for r in rows]


def package_peer_prices(dest_key: str, days_back: int = 30) -> list[int]:
    """같은 목적지 상품들의 가격. 상품마다 최신 1건씩만 세어 중복을 막는다."""
    if not dest_key:
        return []
    since = int(time.time()) - days_back * 86400
    with db() as conn:
        rows = conn.execute(
            "SELECT price FROM package_obs p WHERE dest_key=? AND observed_at>=?"
            " AND observed_at = (SELECT MAX(observed_at) FROM package_obs q"
            "                    WHERE q.source=p.source AND q.code=p.code)",
            (dest_key, since),
        ).fetchall()
    return [r["price"] for r in rows]


def purge_old_packages(days_keep: int = 180) -> int:
    cutoff = int(time.time()) - days_keep * 86400
    with db() as conn:
        cur = conn.execute("DELETE FROM package_obs WHERE observed_at < ?", (cutoff,))
        return cur.rowcount


# ── 기후 캐시 ────────────────────────────────────────────────────────
def get_climate(iata: str, max_age_days: int = 30) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT fetched_at, payload FROM climate_cache WHERE iata=?", (iata,)
        ).fetchone()
    if not row:
        return None
    if time.time() - row["fetched_at"] > max_age_days * 86400:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def put_climate(iata: str, payload: dict) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO climate_cache (iata, fetched_at, payload) VALUES (?,?,?)"
            " ON CONFLICT(iata) DO UPDATE SET fetched_at=excluded.fetched_at,"
            " payload=excluded.payload",
            (iata, int(time.time()), json.dumps(payload, ensure_ascii=False)),
        )


# ── 발송 중복 방지 ───────────────────────────────────────────────────
def recently_alerted(key: str, cooldown_hours: int, price: int) -> bool:
    """쿨다운 안에 같은 건을 보낸 적이 있으면 True.

    단, 지난번보다 5% 넘게 더 싸졌으면 다시 보낸다.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT sent_at, price FROM alerts_sent WHERE key=?", (key,)
        ).fetchone()
    if not row:
        return False
    if time.time() - row["sent_at"] > cooldown_hours * 3600:
        return False
    return price > row["price"] * 0.95


def mark_alerted(key: str, price: int) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO alerts_sent (key, sent_at, price) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET sent_at=excluded.sent_at, price=excluded.price",
            (key, int(time.time()), int(price)),
        )


# ── 구독자 ───────────────────────────────────────────────────────────
def add_subscriber(chat_id: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO subscribers (chat_id, added_at, enabled) VALUES (?,?,1)"
            " ON CONFLICT(chat_id) DO UPDATE SET enabled=1",
            (str(chat_id), int(time.time())),
        )


def remove_subscriber(chat_id: str) -> None:
    with db() as conn:
        conn.execute("UPDATE subscribers SET enabled=0 WHERE chat_id=?", (str(chat_id),))


def scrub_private() -> int:
    """공개 저장소에 올리기 전, DB에서 개인 정보를 지운다.

    가격 이력은 깃허브에 커밋해야 '평소 가격'이 쌓인다. 그런데 같은 파일에
    내 텔레그램 chat_id 가 들어 있어서 그대로 올리면 공개된다.
    깃허브에서 돌 때 받는 사람은 TELEGRAM_CHAT_ID 환경변수로 들어오므로
    DB에 남길 필요가 없다.
    """
    with db() as conn:
        n = conn.execute("DELETE FROM subscribers").rowcount
        conn.execute("DELETE FROM meta WHERE key='tg_offset'")

    # DELETE 만으로는 안 지워진다. 지운 자리가 빈 공간으로 남고 옛 값이 파일에
    # 그대로 남아 있어서, 표에는 안 보여도 파일을 열어 보면 읽힌다.
    # VACUUM 이 파일을 처음부터 다시 써야 진짜로 사라진다.
    vac = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        vac.execute("VACUUM")
    finally:
        vac.close()
    return n


def subscribers() -> list[str]:
    with db() as conn:
        rows = conn.execute("SELECT chat_id FROM subscribers WHERE enabled=1").fetchall()
    ids = [r["chat_id"] for r in rows]
    if config.TELEGRAM_CHAT_ID and config.TELEGRAM_CHAT_ID not in ids:
        ids.append(config.TELEGRAM_CHAT_ID)
    return ids


# ── 메타 ─────────────────────────────────────────────────────────────
def set_meta(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def stats() -> dict:
    with db() as conn:
        obs = conn.execute("SELECT COUNT(*) c FROM price_obs").fetchone()["c"]
        routes = conn.execute(
            "SELECT COUNT(DISTINCT destination) c FROM price_obs"
        ).fetchone()["c"]
        oldest = conn.execute("SELECT MIN(observed_at) m FROM price_obs").fetchone()["m"]
        pkgs = conn.execute("SELECT COUNT(*) c FROM package_obs").fetchone()["c"]
        pkg_codes = conn.execute(
            "SELECT COUNT(DISTINCT source || code) c FROM package_obs"
        ).fetchone()["c"]
    return {"observations": obs, "routes": routes, "oldest": oldest,
            "packages": pkgs, "package_products": pkg_codes}
