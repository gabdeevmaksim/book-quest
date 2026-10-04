"""Engine unit tests: pricing, monthly budget ledger, usage plumbing. No API calls."""
import time

import pytest

import story_engine as E


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "USAGE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setenv("QUEST_MONTHLY_BUDGET_USD", "5")


def test_pricing(monkeypatch):
    assert E.estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)
    assert E.estimate_cost("gemini-2.5-flash", 1_000_000, 1_000_000) == 0.0   # free backup
    assert E.estimate_cost("unknown-model", 1_000_000, 1_000_000) == 0.0
    monkeypatch.delenv("QUEST_GOOGLE_TIER", raising=False)                      # default: free tier
    assert E.estimate_cost("gemini-3.8-flash", 1_000_000, 1_000_000) == 0.0
    monkeypatch.setenv("QUEST_GOOGLE_TIER", "paid")
    assert E.estimate_cost("gemini-3.8-flash", 1_000_000, 1_000_000) == pytest.approx(4.5)


def test_default_chains_are_free_gemini(monkeypatch):
    for v in ("QUEST_GEN_MODELS", "QUEST_GEN_MODEL", "QUEST_REVIEW_MODELS"):
        monkeypatch.delenv(v, raising=False)
    writers, reviewers = E.gen_models("google"), E.review_models("google")
    assert writers[0] == "gemini-3.8-flash"
    assert all(m.endswith("-lite") for m in reviewers)                 # reviews use Flash Lite (500/day)
    assert not any(m.endswith("-lite") for m in writers)               # so they never eat writing quota
    assert all(m.startswith("gemini") and "pro" not in m for m in writers + reviewers)
    import quota as Q
    assert all(Q.tracked(m) for m in writers + reviewers)              # every default has a known limit


def test_budget_cap_and_monthly_rollover():
    assert E.monthly_budget() == 5.0
    assert E.month_spend() == 0.0 and not E.budget_exceeded()
    E.record_spend(2.0, "claude-sonnet-4-6", 100, 200)
    assert E.month_spend() == pytest.approx(2.0) and not E.budget_exceeded()
    E.record_spend(4.0, "claude-sonnet-4-6", 100, 200)
    assert E.budget_exceeded()
    prev_month = time.time() - 60 * 24 * 3600
    E.record_spend(99.0, "claude-opus-4-8", when=prev_month)
    assert E.month_spend() == pytest.approx(6.0)            # last month doesn't count
    assert E.month_spend(prev_month) == pytest.approx(99.0)


def test_budget_off_when_unset(monkeypatch):
    monkeypatch.delenv("QUEST_MONTHLY_BUDGET_USD")
    E.record_spend(1000.0)
    assert not E.budget_exceeded()


def test_create_story_attaches_usage(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "gate_report", lambda p, d: (
        True, [], {"correctness": True, "coherence": True, "balance": "PASS", "bal_lines": []}))
    story = ('{"title":"T","character_template":{"health":18,"strength":10,"agility":10,'
             '"stamina":10},"start_location_id":"s","locations":{"s":{"description":"d",'
             '"is_end":true,"is_victory":true,"choices":[]}}}')
    out = tmp_path / "t.json"
    ok, path, summary = E.create_story("theme", "normal", api_key="x", out_path=str(out),
                                       model_call=lambda system, messages: story, review=False)
    assert ok and path == str(out) and out.exists()
    for key in ("cost_usd", "tokens_in", "tokens_out", "attempts", "model_used"):
        assert key in summary
