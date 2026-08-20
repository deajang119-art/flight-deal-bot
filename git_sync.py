# -*- coding: utf-8 -*-
"""PC 스캔 앞뒤로 저장소와 가격 이력 DB(data/deals.db)를 맞춘다.

    python git_sync.py pull    # 스캔 전 — 깃허브(Actions)가 남긴 최신 이력을 받아온다
    python git_sync.py push    # 스캔 후 — 이번 스캔 결과를 저장소에 올린다

왜 필요한가
    알림 중복을 막는 장치는 DB 안의 alerts_sent(발송 이력)다. PC와 깃허브가
    각자 다른 DB를 보면 서로 무엇을 보냈는지 몰라 같은 특가를 두 번 보낸다.
    스캔 전에 당겨 오고 스캔 후에 올려 두면 두 곳이 같은 이력을 본다.

원칙
    - 정상 흐름은 fast-forward 한 번이면 끝난다(PC가 올린 걸 깃허브가 받아
      이어서 올리고, PC가 다시 받는 구조라 갈라질 일이 없다).
    - 그래도 갈라졌다면 원격을 정본으로 삼되, 로컬의 발송 이력만 합친다.
      가격 관측 한 번은 잃어도 되지만 발송 이력을 잃으면 중복 알림이 난다.
    - 어떤 실패도 스캔 자체를 막지 않는다. 동기화가 안 되면 경고만 남기고
      평소처럼 스캔한다(알림이 안 가는 것보다 중복이 낫다).
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "deals.db")
TIMEOUT = 90  # 초. 자격증명 창이 떠도 작업이 매달려 있지 않게 한다.

ENV = dict(os.environ)
ENV["GIT_TERMINAL_PROMPT"] = "0"     # 터미널에서 아이디/비번을 묻지 않는다
ENV["GCM_INTERACTIVE"] = "Never"     # 윈도우 자격증명 관리자 창도 띄우지 않는다


def log(msg):
    print("[sync %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def git(*args, **kw):
    """git 명령 하나. (성공여부, 출력) 을 돌려준다."""
    try:
        p = subprocess.run(["git"] + list(args), cwd=HERE, env=ENV,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        log("시간초과: git " + " ".join(args))
        return False, ""
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0 and not kw.get("quiet"):
        log("실패(%d): git %s → %s" % (p.returncode, " ".join(args), out.splitlines()[-1] if out else ""))
    return p.returncode == 0, out


def db_dirty():
    ok, out = git("status", "--porcelain", "--", "data/deals.db", quiet=True)
    return ok and bool(out.strip())


def commit_db(tag):
    git("add", "-f", "data/deals.db")
    staged_clean, _ = git("diff", "--staged", "--quiet", quiet=True)
    if staged_clean:                      # 종료코드 0 = 바뀐 것 없음
        return False
    msg = "가격 이력 갱신(PC) %s" % time.strftime("%Y-%m-%d %H:%M")
    ok, _ = git("commit", "-m", msg)
    if ok:
        log("커밋함 — %s" % tag)
    return ok


def merge_alerts(backup_path):
    """백업 DB의 발송 이력을 현재 DB에 합친다. 최신 발송 시각이 이긴다."""
    if not os.path.exists(backup_path) or not os.path.exists(DB):
        return 0
    conn = sqlite3.connect(DB)
    try:
        conn.execute("ATTACH DATABASE ? AS bak", (backup_path,))
        n = conn.execute("""
            INSERT INTO alerts_sent (key, sent_at, price)
            SELECT key, sent_at, price FROM bak.alerts_sent
            WHERE true
            ON CONFLICT(key) DO UPDATE SET
                sent_at = MAX(alerts_sent.sent_at, excluded.sent_at),
                price   = CASE WHEN excluded.sent_at > alerts_sent.sent_at
                               THEN excluded.price ELSE alerts_sent.price END
        """).rowcount
        conn.commit()
        conn.execute("DETACH DATABASE bak")
        return n
    except sqlite3.Error as e:
        log("발송 이력 병합 실패: %s" % e)
        return 0
    finally:
        conn.close()


def pull():
    """스캔 전 — 원격의 최신 이력을 받아 온다."""
    if not os.path.isdir(os.path.join(HERE, ".git")):
        log("저장소가 아니다. 건너뛴다.")
        return
    if db_dirty():                        # 지난 스캔이 push 못 하고 끝난 경우
        commit_db("지난 스캔 뒷정리")
    if not git("fetch", "origin", "main")[0]:
        log("가져오기 실패 — 네트워크? 이번 스캔은 로컬 이력만으로 진행한다.")
        return
    ok, _ = git("merge", "--ff-only", "origin/main", quiet=True)
    if ok:
        log("최신 이력 반영 완료")
        return
    # 여기부터는 갈라진 경우. 원격을 정본으로 삼고 발송 이력만 건진다.
    log("로컬과 원격이 갈라졌다 → 원격을 기준으로 맞추고 발송 이력만 합친다")
    bak = os.path.join(tempfile.gettempdir(), "deals_local_%d.db" % int(time.time()))
    try:
        shutil.copy2(DB, bak)
    except OSError:
        bak = None
    if not git("reset", "--hard", "origin/main")[0]:
        log("원격 기준 맞추기 실패 — 로컬 이력 그대로 스캔한다")
        return
    if bak:
        log("발송 이력 %d건 합침" % merge_alerts(bak))
        try:
            os.remove(bak)
        except OSError:
            pass


def push():
    """스캔 후 — 이번 결과를 올린다. 올리기 전에 개인정보를 지운다."""
    if not os.path.isdir(os.path.join(HERE, ".git")):
        return
    try:
        import storage
        storage.init()
        storage.scrub_private()           # 공개 저장소이므로 chat_id 등 제거 + VACUUM
    except Exception as e:                # 스크럽 실패 시 절대 올리지 않는다
        log("개인정보 제거 실패(%s) — 올리지 않는다" % e)
        return
    if not commit_db("스캔 결과"):
        log("바뀐 이력 없음")
        return
    git("pull", "--rebase", "--autostash", quiet=True)   # 그 사이 깃허브가 올렸을 수 있다
    if git("push", "origin", "main")[0]:
        log("저장소에 올림")
    else:
        log("올리기 실패 — 다음 스캔 때 다시 시도한다(커밋은 남아 있다)")


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if cmd == "pull":
        pull()
    elif cmd == "push":
        push()
    else:
        print(__doc__)
        sys.exit(1)
