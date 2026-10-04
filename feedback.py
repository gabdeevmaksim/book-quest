#!/usr/bin/env python3
"""
feedback.py — player feedback for Quest Book. Streamlit-free, so it's unit-testable and has a CLI.

Every submission is
  1. appended to a JSON-lines file on the server (always — nothing is ever lost), and
  2. sent to the owner's Telegram chat, if a bot is configured.
It never raises into the app: failures are reported in the returned dict.

Config (environment, read at call time):
  QUEST_FEEDBACK_FILE             default state/feedback.jsonl (gitignored; persists across deploys)
  QUEST_TG_BOT_TOKEN              Telegram bot token from @BotFather   ┐ both set → instant
  QUEST_TG_CHAT_ID                your chat id (see DEPLOY.md)          ┘ Telegram notification
  QUEST_FEEDBACK_NOTIFY_PER_HOUR  cap on Telegram messages per hour (default 30); over the cap,
                                  feedback is still saved to the file

CLI (on the droplet: `docker compose exec quest-book python3 feedback.py`):
  python3 feedback.py                  # latest 20 entries
  python3 feedback.py -n 50 --kind bug
"""
import argparse
import collections
import json
import os
import threading
import time
import urllib.parse
import urllib.request

KINDS = {"bug": "🐞 Bug", "story": "📖 Story", "idea": "💡 Idea", "other": "💬 Other"}
MAX_MESSAGE = 2000
MAX_CONTACT = 120

_lock = threading.Lock()
_sent_times = collections.deque()      # timestamps of Telegram notifications (hourly cap)


def feedback_file():
    return os.environ.get("QUEST_FEEDBACK_FILE") or os.path.join("state", "feedback.jsonl")


def telegram_configured():
    return bool(os.environ.get("QUEST_TG_BOT_TOKEN", "").strip()
                and os.environ.get("QUEST_TG_CHAT_ID", "").strip())


def make_entry(kind, message, rating=None, contact="", context=None, now=None):
    """Normalise one submission into the stored record."""
    try:
        rating = int(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating = None
    if rating is not None and not 1 <= rating <= 5:
        rating = None
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "kind": kind if kind in KINDS else "other",
        "rating": rating,
        "message": (message or "").strip()[:MAX_MESSAGE],
        "contact": (contact or "").strip()[:MAX_CONTACT],
        "context": dict(context or {}),
    }


def save(entry):
    """Append one entry to the feedback file. Returns (ok, path_or_error)."""
    path = feedback_file()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True, path
    except Exception as e:
        return False, f"could not save feedback: {e}"


def format_message(entry):
    """Plain-text rendering used for Telegram and the CLI."""
    head = KINDS.get(entry.get("kind"), KINDS["other"])
    r = entry.get("rating")
    if r:
        head += "   " + "★" * r + "☆" * (5 - r)
    lines = [head]
    if entry.get("message"):
        lines += ["", entry["message"]]
    if entry.get("contact"):
        lines += ["", f"✉ {entry['contact']}"]
    c = entry.get("context") or {}
    meta = []
    if c.get("story"):
        extra = ", ".join(x for x in (c.get("difficulty"), c.get("language")) if x)
        meta.append(f"📖 {c['story']}" + (f" ({extra})" if extra else ""))
    if c.get("location"):
        meta.append(f"📍 {c['location']}")
    if c.get("hp"):
        meta.append(f"❤ {c['hp']}")
    if c.get("outcome"):
        meta.append(c["outcome"])
    if not c.get("story") and c.get("screen"):
        meta.append(f"screen: {c['screen']}")
    if meta:
        lines += ["", " · ".join(meta)]
    tail = entry.get("ts", "") + (f" · v {c['version']}" if c.get("version") else "")
    lines.append(tail.strip(" ·"))
    return "\n".join(lines)


def _notify_allowed(now=None):
    try:
        cap = int(os.environ.get("QUEST_FEEDBACK_NOTIFY_PER_HOUR", "30") or 30)
    except ValueError:
        cap = 30
    now = now or time.time()
    with _lock:
        while _sent_times and now - _sent_times[0] > 3600:
            _sent_times.popleft()
        if len(_sent_times) >= cap:
            return False
        _sent_times.append(now)
        return True


def notify_telegram(entry, timeout=6):
    """Send the entry to the owner's Telegram. Returns (ok, detail). Never raises."""
    token = os.environ.get("QUEST_TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("QUEST_TG_CHAT_ID", "").strip()
    if not (token and chat):
        return False, "Telegram not configured"
    if not _notify_allowed():
        return False, "hourly Telegram limit reached (saved to file)"
    data = urllib.parse.urlencode({
        "chat_id": chat,
        "text": format_message(entry)[:4000],          # Telegram limit is 4096 chars
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = bool(json.loads(resp.read().decode("utf-8")).get("ok"))
        return ok, "sent" if ok else "Telegram rejected the message"
    except Exception as e:
        return False, "Telegram error: " + str(e).replace(token, "***")[:200]


def submit(kind, message, rating=None, contact="", context=None):
    """Save + notify. Returns {saved, notified, detail, entry}. Never raises."""
    entry = make_entry(kind, message, rating, contact, context)
    saved, where = save(entry)
    notified, detail = notify_telegram(entry)
    return {"saved": saved, "notified": notified,
            "detail": detail if saved else where, "entry": entry}


def read_entries(path=None):
    path = path or feedback_file()
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def main():
    ap = argparse.ArgumentParser(description="Show player feedback saved by Quest Book.")
    ap.add_argument("-n", type=int, default=20, help="how many of the latest entries (default 20)")
    ap.add_argument("--kind", choices=sorted(KINDS), help="only this kind")
    ap.add_argument("--file", default=None, help=f"feedback file (default {feedback_file()})")
    args = ap.parse_args()
    entries = [e for e in read_entries(args.file) if not args.kind or e.get("kind") == args.kind]
    if not entries:
        print("No feedback yet.")
        return
    for e in entries[-args.n:]:
        print("─" * 60)
        print(format_message(e))
    print("─" * 60)
    print(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} total"
          + (f" ({args.kind})" if args.kind else ""))


if __name__ == "__main__":
    main()
