#!/usr/bin/env python3
"""
visits.py — a tiny, privacy-friendly visit counter for Quest Book (Streamlit-free).

  • a VISIT  = one browser session opening the app (app.py calls record_visit once per session);
  • a VISITOR = one anonymous id: a SALTED hash of the IP address (or of a random per-session id
    when the IP is unknown). Raw IPs are never stored; the salt lives in state/ and never leaves
    the server, so the hashes can't be turned back into addresses.

Stored in SQLite (state/visits.db — stdlib, safe with several app threads and the CLI at once).
Days are counted in QUEST_STATS_TZ (default Europe/Stockholm).

Streamlit only creates a session when a real browser opens the websocket, so health checks,
link previews (Telegram/WhatsApp) and most crawlers are not counted.

CLI (on the droplet):  docker-compose exec quest-book python3 visits.py      # last 14 days
                       docker-compose exec quest-book sh -c "python3 visits.py 60"
"""
import datetime
import hashlib
import os
import secrets
import sqlite3
import sys

try:
    from zoneinfo import ZoneInfo
except Exception:                                   # pragma: no cover
    ZoneInfo = None


def db_path():
    return os.environ.get("QUEST_VISITS_DB") or os.path.join("state", "visits.db")


def _salt():
    path = os.path.join(os.path.dirname(db_path()) or ".", "visits.salt")
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
            if s:
                return s
    except OSError:
        pass
    s = secrets.token_hex(16)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(s)
    except OSError:
        pass
    return s


def visitor_hash(raw_id):
    return hashlib.sha256((_salt() + "|" + str(raw_id)).encode()).hexdigest()[:20]


def today(now=None):
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(os.environ.get("QUEST_STATS_TZ", "Europe/Stockholm"))
        except Exception:
            tz = None
    dt = datetime.datetime.now(tz) if now is None else datetime.datetime.fromtimestamp(now, tz)
    return dt.strftime("%Y-%m-%d")


def _connect():
    os.makedirs(os.path.dirname(db_path()) or ".", exist_ok=True)
    con = sqlite3.connect(db_path(), timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS visits (day TEXT PRIMARY KEY, n INTEGER NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS visitors (visitor TEXT NOT NULL, day TEXT NOT NULL, "
                "PRIMARY KEY (visitor, day))")
    return con


def record_visit(raw_id, now=None):
    """Count one visit by this visitor (raw IP or session id — hashed here). Never raises."""
    try:
        day, v = today(now), visitor_hash(raw_id)
        con = _connect()
        with con:
            con.execute("INSERT INTO visits(day, n) VALUES (?, 1) "
                        "ON CONFLICT(day) DO UPDATE SET n = n + 1", (day,))
            con.execute("INSERT OR IGNORE INTO visitors(visitor, day) VALUES (?, ?)", (v, day))
        con.close()
        return True
    except Exception:
        return False


def totals(now=None):
    """{'visits', 'visitors' (all time, unique), 'visits_today', 'visitors_today'}."""
    try:
        con = _connect()
        day = today(now)
        r = {
            "visits": con.execute("SELECT COALESCE(SUM(n), 0) FROM visits").fetchone()[0],
            "visitors": con.execute("SELECT COUNT(DISTINCT visitor) FROM visitors").fetchone()[0],
            "visits_today": (con.execute("SELECT n FROM visits WHERE day = ?", (day,)).fetchone()
                             or [0])[0],
            "visitors_today": con.execute("SELECT COUNT(*) FROM visitors WHERE day = ?",
                                          (day,)).fetchone()[0],
        }
        con.close()
        return r
    except Exception:
        return {"visits": 0, "visitors": 0, "visits_today": 0, "visitors_today": 0}


def daily(days=14):
    """[(day, visits, unique visitors)] for the most recent `days` days with traffic."""
    con = _connect()
    rows = con.execute(
        "SELECT v.day, v.n, (SELECT COUNT(*) FROM visitors u WHERE u.day = v.day) "
        "FROM visits v ORDER BY v.day DESC LIMIT ?", (int(days),)).fetchall()
    con.close()
    return rows


def main(argv):
    days = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 14
    t = totals()
    print(f"All time: {t['visits']} visits · {t['visitors']} unique visitors")
    print(f"Today:    {t['visits_today']} visits · {t['visitors_today']} unique visitors\n")
    print(f"{'day':12s} {'visits':>7s} {'unique':>7s}")
    for day, n, u in daily(days):
        print(f"{day:12s} {n:>7d} {u:>7d}")


if __name__ == "__main__":
    main(sys.argv)
