"""feedback.py: storage, Telegram notification (mocked — no network), limits."""
import io
import json
import urllib.parse

import pytest

import feedback as F

TOKEN = "123456:SECRET-token"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("QUEST_FEEDBACK_FILE", str(tmp_path / "feedback.jsonl"))
    monkeypatch.delenv("QUEST_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("QUEST_TG_CHAT_ID", raising=False)
    monkeypatch.delenv("QUEST_FEEDBACK_NOTIFY_PER_HOUR", raising=False)
    F._sent_times.clear()


def _with_telegram(monkeypatch, calls, reply=b'{"ok": true}', error=None):
    monkeypatch.setenv("QUEST_TG_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("QUEST_TG_CHAT_ID", "42")

    def fake_urlopen(req, timeout=None):
        if error:
            raise error
        calls.append((req.full_url, urllib.parse.parse_qs(req.data.decode())))
        return io.BytesIO(reply)
    monkeypatch.setattr(F.urllib.request, "urlopen", fake_urlopen)


def test_make_entry_normalises_input():
    e = F.make_entry("weird", "  hi  " + "x" * 5000, rating=9, contact="c" * 500)
    assert e["kind"] == "other" and e["rating"] is None
    assert e["message"].startswith("hi") and len(e["message"]) == F.MAX_MESSAGE
    assert len(e["contact"]) == F.MAX_CONTACT
    assert F.make_entry("bug", "m", rating="4")["rating"] == 4


def test_saved_to_file_without_telegram():
    res = F.submit("bug", "the door never opens", 2, "me@x", {"story": "Catacombs"})
    assert res["saved"] and not res["notified"] and res["detail"] == "Telegram not configured"
    [entry] = F.read_entries()
    assert entry["message"] == "the door never opens" and entry["context"]["story"] == "Catacombs"


def test_telegram_notification(monkeypatch):
    calls = []
    _with_telegram(monkeypatch, calls)
    res = F.submit("story", "loved it", 5, "", {"story": "Silent Run", "hp": "7/18"})
    assert res["saved"] and res["notified"]
    url, form = calls[0]
    assert url.endswith(f"/bot{TOKEN}/sendMessage") and form["chat_id"] == ["42"]
    assert "★★★★★" in form["text"][0] and "Silent Run" in form["text"][0]


def test_telegram_error_is_reported_without_leaking_token(monkeypatch):
    _with_telegram(monkeypatch, [], error=OSError(f"boom at /bot{TOKEN}/"))
    res = F.submit("bug", "x")
    assert res["saved"] and not res["notified"]
    assert TOKEN not in res["detail"] and "***" in res["detail"]


def test_hourly_notification_cap_still_saves(monkeypatch):
    calls = []
    _with_telegram(monkeypatch, calls)
    monkeypatch.setenv("QUEST_FEEDBACK_NOTIFY_PER_HOUR", "2")
    results = [F.submit("idea", f"idea {i}") for i in range(3)]
    assert [r["notified"] for r in results] == [True, True, False]
    assert len(F.read_entries()) == 3 and len(calls) == 2


def test_format_message_lists_context():
    text = F.format_message(F.make_entry("bug", "stuck", 1, "tg @me", {
        "story": "Banshee", "difficulty": "hard", "language": "English",
        "location": "deck", "hp": "3/12", "outcome": "playing", "version": "abc123"}))
    for part in ("🐞 Bug", "★☆☆☆☆", "stuck", "@me", "Banshee (hard, English)", "deck", "3/12", "abc123"):
        assert part in text
