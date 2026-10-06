"""Engine unit tests: pricing, monthly budget ledger, usage plumbing. No API calls."""
import time

import pytest

import story_engine as E


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "USAGE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setenv("QUEST_MONTHLY_BUDGET_USD", "5")
    for v in ("QUEST_MONTHLY_BUDGET", "QUEST_BUDGET_CURRENCY", "QUEST_USD_RATE"):
        monkeypatch.delenv(v, raising=False)


def test_pricing(monkeypatch):
    assert E.estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)
    assert E.estimate_cost("unknown-model", 1_000_000, 1_000_000) == 0.0
    monkeypatch.delenv("QUEST_GOOGLE_TIER", raising=False)                      # default: paid (Tier 1)
    assert E.google_tier() == "paid"
    assert E.estimate_cost("gemini-3.8-flash", 1_000_000, 1_000_000) == pytest.approx(4.5)
    assert E.estimate_cost("gemini-2.5-flash-lite", 1_000_000, 1_000_000) == pytest.approx(0.5)
    monkeypatch.setenv("QUEST_GOOGLE_TIER", "free")
    assert E.estimate_cost("gemini-3.8-flash", 1_000_000, 1_000_000) == 0.0
    assert E.estimate_cost("gemini-2.5-flash", 1_000_000, 1_000_000) == 0.0


def test_every_default_model_has_a_price(monkeypatch):
    for v in ("QUEST_GEN_MODELS", "QUEST_GEN_MODEL", "QUEST_REVIEW_MODELS"):
        monkeypatch.delenv(v, raising=False)
    for p in ("google", "anthropic"):
        for m in E.gen_models(p) + E.review_models(p):
            assert E.MODEL_PRICING.get(m, (0, 0))[1] > 0, m     # unknown price would count as $0


def test_budget_fallback_needs_a_free_key(monkeypatch):
    for v in ("QUEST_GOOGLE_FREE_API_KEY", "QUEST_FREE_FALLBACK_MODELS"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "paid-key")
    monkeypatch.setenv("QUEST_GOOGLE_TIER", "paid")
    assert E.budget_fallback_models() == []                    # one paid key: pause at the cap
    monkeypatch.setenv("QUEST_GOOGLE_FREE_API_KEY", "free-key")
    assert E.budget_fallback_models()[0] == "gemini-3.8-flash"  # free project: whole Flash rotation
    assert E.env_api_key("google") == "paid-key"
    with E.free_tier():                                        # inside: free key, free limits, $0
        assert E.env_api_key("google") == "free-key"
        assert E.estimate_cost("gemini-3.8-flash", 1_000_000, 1_000_000) == 0.0
        assert E.Q.limits()["gemini-3.8-flash"]["rpd"] == 20
    assert E.env_api_key("google") == "paid-key" and E.Q.tier() == "paid"
    monkeypatch.delenv("QUEST_GOOGLE_FREE_API_KEY")
    monkeypatch.setenv("QUEST_GOOGLE_TIER", "free")
    assert E.budget_fallback_models()                          # the main key is free already


def test_budget_in_another_currency(monkeypatch):
    monkeypatch.delenv("QUEST_MONTHLY_BUDGET_USD", raising=False)
    monkeypatch.setenv("QUEST_BUDGET_CURRENCY", "SEK")
    monkeypatch.setenv("QUEST_USD_RATE", "10")
    monkeypatch.setenv("QUEST_MONTHLY_BUDGET", "150")
    assert E.monthly_budget() == pytest.approx(15.0)           # ledger stays in USD
    assert E.money(1.5) == "15.00 kr" and E.money(0.0123, 3) == "0.123 kr"
    E.record_spend(10.0)
    assert E.budget_left() == pytest.approx(5.0) and not E.budget_exceeded()
    monkeypatch.setenv("QUEST_BUDGET_CURRENCY", "USD")
    monkeypatch.setenv("QUEST_MONTHLY_BUDGET", "0")
    assert E.budget_left() is None and E.money(2) == "$2.00"


class _Overloaded(Exception):
    pass


def _fake_gemini(monkeypatch, script):
    """Install a fake google.genai whose generate_content follows `script` (per model: a list of
    'ok' / error strings, consumed in order)."""
    import sys
    import types as pytypes
    calls = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            step = script[model].pop(0)
            if step != "ok":
                raise _Overloaded(step)
            return pytypes.SimpleNamespace(text="{}", usage_metadata=pytypes.SimpleNamespace(
                prompt_token_count=10, candidates_token_count=5))

    genai = pytypes.ModuleType("google.genai")
    genai.Client = lambda api_key=None: pytypes.SimpleNamespace(models=Models())
    gtypes = pytypes.ModuleType("google.genai.types")
    for name in ("Content", "Part", "GenerateContentConfig"):
        setattr(gtypes, name, lambda *a, **k: None)
    genai.types = gtypes
    google = pytypes.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    return calls


@pytest.fixture
def quiet_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("QUEST_QUOTA_FILE", str(tmp_path / "quota.json"))
    monkeypatch.setenv("QUEST_GOOGLE_TIER", "paid")
    slept = []
    monkeypatch.setattr(E, "_sleep", slept.append)
    return slept


def test_overload_is_waited_out_on_the_best_model(monkeypatch, quiet_quota):
    monkeypatch.setenv("QUEST_OVERLOAD_PATIENCE", "60")
    calls = _fake_gemini(monkeypatch, {"gemini-3.8-flash": ["503 UNAVAILABLE", "503 UNAVAILABLE", "ok"]})
    text, used = E.call_with_fallback("google", ["gemini-3.8-flash", "gemini-3.7-flash"], "s",
                                      [{"role": "user", "content": "x"}], "k")
    assert used == "gemini-3.8-flash" and calls == ["gemini-3.8-flash"] * 3
    assert len(quiet_quota) == 2 and 4 <= quiet_quota[0] <= 6 and 8 <= quiet_quota[1] <= 12


def test_patience_runs_out_then_next_model_and_circuit_breaker(monkeypatch, quiet_quota):
    import quota as Q
    monkeypatch.setenv("QUEST_OVERLOAD_PATIENCE", "20")        # 5 + 10 fit, the 20 s pause doesn't
    calls = _fake_gemini(monkeypatch, {"gemini-3.8-flash": ["503 UNAVAILABLE"] * 3,
                                       "gemini-3.7-flash": ["ok", "ok"]})
    msgs = [{"role": "user", "content": "x"}]
    _, used = E.call_with_fallback("google", ["gemini-3.8-flash", "gemini-3.7-flash"], "s", msgs, "k")
    assert used == "gemini-3.7-flash" and calls == ["gemini-3.8-flash"] * 3 + ["gemini-3.7-flash"]
    assert Q.overloaded("gemini-3.8-flash")                    # 3 × 503 → tried last for a while
    assert Q.healthy_first(["gemini-3.8-flash", "gemini-3.7-flash"])[0] == "gemini-3.7-flash"
    _, used = E.call_with_fallback("google", ["gemini-3.8-flash", "gemini-3.7-flash"], "s", msgs, "k")
    assert used == "gemini-3.7-flash" and calls[-1] == "gemini-3.7-flash"   # no wait on 3.8 this time


def test_bad_request_is_not_retried(monkeypatch, quiet_quota):
    calls = _fake_gemini(monkeypatch, {"gemini-3.8-flash": ["400 INVALID_ARGUMENT", "ok"]})
    with pytest.raises(_Overloaded):
        E.call_model("google", "gemini-3.8-flash", "s", [{"role": "user", "content": "x"}], "k")
    assert calls == ["gemini-3.8-flash"] and quiet_quota == []


def test_default_chains_are_gemini_flash(monkeypatch):
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
