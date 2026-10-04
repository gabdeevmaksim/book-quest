"""quota.py — free-tier rate limiting (fake clock: no real waiting, no API calls)."""
import datetime
import json

import pytest

import quota as Q
import story_engine as E

T0 = 1_791_000_000.0          # a fixed moment (Oct 2026)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("QUEST_QUOTA_FILE", str(tmp_path / "quota.json"))
    monkeypatch.delenv("QUEST_MODEL_LIMITS", raising=False)
    monkeypatch.delenv("QUEST_STORIES_PER_PLAYER", raising=False)


def _limits(monkeypatch, **models):
    monkeypatch.setenv("QUEST_MODEL_LIMITS", json.dumps(models))


def test_daily_limit_skips_the_model(monkeypatch):
    _limits(monkeypatch, **{"gemini-3.8-flash": {"rpm": 100, "rpd": 3}})
    c = Clock()
    assert [Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)[0] for _ in range(3)] == [True] * 3
    ok, why = Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)
    assert not ok and "daily limit" in why


def test_per_minute_limit_waits_or_skips(monkeypatch):
    _limits(monkeypatch, **{"gemini-3.8-flash": {"rpm": 2, "rpd": 100}})
    c = Clock()
    Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)
    Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)
    ok, _ = Q.reserve("gemini-3.8-flash", wait_limit=120, clock=c, sleep=c.sleep)
    assert ok and c.t - T0 >= 60                                  # waited for the window
    Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)
    ok, why = Q.reserve("gemini-3.8-flash", wait_limit=5, clock=c, sleep=c.sleep)
    assert not ok and "per-minute" in why                         # won't wait that long → skip


def test_new_pacific_day_resets_counters(monkeypatch):
    _limits(monkeypatch, **{"gemini-3.8-flash": {"rpm": 100, "rpd": 1}})
    c = Clock()
    assert Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)[0]
    assert not Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)[0]
    c.t += Q.seconds_until_reset(c.t) + 5                         # just past midnight Pacific
    assert Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)[0]


def test_learns_from_api_errors():
    c = Clock()
    Q.note_error("gemini-3.8-flash", "429 RESOURCE_EXHAUSTED: quota exceeded per day", clock=c)
    assert not Q.reserve("gemini-3.8-flash", clock=c, sleep=c.sleep)[0]
    Q.note_error("gemini-3.7-flash", "429 RESOURCE_EXHAUSTED: rate limit", clock=c)   # per-minute
    ok, why = Q.reserve("gemini-3.7-flash", wait_limit=5, clock=c, sleep=c.sleep)
    assert not ok and "per-minute" in why
    Q.note_error("gemini-3.6-flash", "404 NOT_FOUND: models/gemini-3.6-flash is not found", clock=c)
    assert not Q.reserve("gemini-3.6-flash", clock=c, sleep=c.sleep)[0]
    assert Q.reserve("claude-sonnet-4-6")[0]                      # untracked → always allowed


def test_capacity_counter_uses_measured_average(monkeypatch):
    _limits(monkeypatch, **{"gemini-3.8-flash": {"rpm": 100, "rpd": 20},
                            "gemini-3.7-flash": {"rpm": 100, "rpd": 20}})
    writers = ["gemini-3.8-flash", "gemini-3.7-flash"]
    assert Q.capacity(writers)["stories"] == 13                   # 40 calls / 3 (default avg)
    for _ in range(3):
        Q.record_run(2, 1)                                        # measured: 2 writer calls/story
    assert Q.capacity(writers)["stories"] == 20
    for _ in range(10):
        Q.reserve("gemini-3.8-flash", wait_limit=0)
    assert Q.capacity(writers)["writer_left"] == 30


def test_per_player_counter():
    Q.record_client("ip:abc")
    Q.record_client("ip:abc")
    assert Q.client_used("ip:abc") == 2 and Q.client_used("ip:other") == 0
    assert Q.stories_per_player() == 3


def test_one_generation_at_a_time():
    with Q.generation_slot(timeout=1) as first:
        assert first
        with Q.generation_slot(timeout=0.3, poll=0.1) as second:
            assert not second                                     # busy → caller shows "queue"
    with Q.generation_slot(timeout=1) as again:
        assert again


def test_model_call_skips_spent_model_without_calling_the_api():
    for m in ("gemini-3.8-flash", "gemini-3.7-flash"):        # real clock: call_model uses it too
        Q.note_error(m, "429 quota exceeded per day")
    with pytest.raises(Q.QuotaSkip):
        E.call_model("google", "gemini-3.8-flash", "sys", [{"role": "user", "content": "x"}], "key")
    with pytest.raises(RuntimeError, match="free-tier quota"):
        E.call_with_fallback("google", ["gemini-3.8-flash", "gemini-3.7-flash"], "sys",
                             [{"role": "user", "content": "x"}], "key")


def test_pacific_clock_without_tz_database():
    july = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)
    jan = datetime.datetime(2026, 1, 15, 12, tzinfo=datetime.timezone.utc)
    assert Q._pacific_offset_hours(july) == -7 and Q._pacific_offset_hours(jan) == -8
    assert 0 <= Q.seconds_until_reset() <= 86400 and len(Q.quota_day()) == 10
