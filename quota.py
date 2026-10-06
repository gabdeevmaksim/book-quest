#!/usr/bin/env python3
"""
quota.py — keeps Quest Book inside the Gemini API rate limits (free tier or paid Tier 1).

QUEST_GOOGLE_TIER picks the table: "paid" (default — billing linked, Tier 1) or "free".
Every model has its OWN budget (AI Studio → Rate limit, project book-quest):

  Free tier (2026-10-04)
    Flash 3.8 / 3.7 / 3.6 / 3.5 / 2.5       5 req/min   250K input tok/min    20 req/day  (each)
    Flash Lite 3.5 / 3.1                    15 req/min   250K input tok/min   500 req/day  (each)
    Flash Lite 2.5                          10 req/min   250K input tok/min    20 req/day
    Pro models                               0 (paid only)
  Tier 1 (2026-10-06)
    Flash 3.8 / 3.7 / 3.6 / 3.5           1000 req/min    2M tok/min       10 000 req/day
    Flash 2.5                             1000 req/min    1M tok/min       10 000 req/day
    Flash Lite                            4000 req/min    4M tok/min      150 000 req/day

On Tier 1 the request limits are far away; the real stop is money (QUEST_MONTHLY_BUDGET_USD),
so capacity() also divides the budget left by the measured cost per story. Google's servers
do get overloaded (503): note_error() remembers a streak of 5xx answers and healthy_first()
moves such a model to the back of the chain for a few minutes.

Limits are per PROJECT (extra keys in the same project don't add quota) and the daily counters
reset at MIDNIGHT PACIFIC TIME.

Strategy (wired in story_engine.py):
  • Writing rotates through the Flash models (≈ 6 × 20 = 120 calls/day); reviewing uses the
    Flash Lite models (500/day each), so checking never eats writing capacity.
  • Before every request `reserve()` counts it locally: if the model's day is used up it is
    skipped (no wasted call), if its per-minute window is full we wait briefly (or skip).
  • Real 429 / 404 answers are learned (`note_error`): per-day → model off until reset,
    per-minute → short cool-down, unknown model → off for the day.
  • One story generation at a time (`generation_slot`) so simultaneous players queue instead of
    tripping the 5-per-minute limit; a per-player daily cap stops one person draining the day.
  • `capacity()` → "≈ N stories can still be created today" from the calls left and the
    measured average calls per story.

State lives in state/quota.json (gitignored, survives deploys); every read-modify-write holds a
file lock, so the app and the CLI scripts (regenerate_library.py, story_agent.py) share it.

Config:  QUEST_QUOTA_FILE (default state/quota.json) · QUEST_MODEL_LIMITS (JSON, overrides/extends
the table, e.g. '{"gemini-3.8-flash": {"rpm": 5, "tpm": 250000, "rpd": 20}}') ·
QUEST_QUOTA_MAX_WAIT (seconds to wait for a per-minute slot, default 65) ·
QUEST_STORIES_PER_PLAYER (daily cap per player, default 3).

CLI:  python3 quota.py                 # today's usage per model + capacity
      python3 quota.py --check-models  # which chain models your key can actually see
      python3 quota.py check-models    # same (use this form through `docker compose exec`)
"""
import contextlib
import contextvars
import datetime
import json
import math
import os
import sys
import time

try:
    import fcntl                                    # POSIX (droplet/container, macOS)
except ImportError:                                 # pragma: no cover — Windows dev boxes
    fcntl = None
try:
    from zoneinfo import ZoneInfo
    PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:                                   # no tz database → DST rule below
    PACIFIC = None

_FLASH = {"rpm": 5, "tpm": 250_000, "rpd": 20}
_LITE = {"rpm": 15, "tpm": 250_000, "rpd": 500}
FREE_LIMITS = {
    "gemini-3.8-flash": _FLASH, "gemini-3.7-flash": _FLASH, "gemini-3.6-flash": _FLASH,
    "gemini-3.5-flash": _FLASH, "gemini-2.5-flash": _FLASH,
    "gemini-3.5-flash-lite": _LITE, "gemini-3.1-flash-lite": _LITE,
    "gemini-2.5-flash-lite": {"rpm": 10, "tpm": 250_000, "rpd": 20},
}
# Tier 1 (billing linked), AI Studio → Rate limit, 2026-10-06. Google also caps Tier 1 spend
# at $250/month; the app's own cap is QUEST_MONTHLY_BUDGET_USD.
_T1_FLASH = {"rpm": 1000, "tpm": 2_000_000, "rpd": 10_000}
_T1_LITE = {"rpm": 4000, "tpm": 4_000_000, "rpd": 150_000}
TIER1_LIMITS = {
    "gemini-3.8-flash": _T1_FLASH, "gemini-3.7-flash": _T1_FLASH, "gemini-3.6-flash": _T1_FLASH,
    "gemini-3.5-flash": _T1_FLASH,
    "gemini-2.5-flash": {"rpm": 1000, "tpm": 1_000_000, "rpd": 10_000},
    "gemini-3.5-flash-lite": _T1_LITE, "gemini-3.1-flash-lite": _T1_LITE,
    "gemini-2.5-flash-lite": _T1_LITE,
}
DEFAULT_LIMITS = FREE_LIMITS        # kept for backwards compatibility (tests, imports)
DEFAULT_AVG_WRITER_CALLS = 3.0      # draft + ~2 repairs, until real runs are measured
DEFAULT_AVG_REVIEW_CALLS = 1.5
DEFAULT_AVG_COST_USD = 0.08         # per story on paid Gemini Flash, until real runs are measured
# Overload circuit breaker: this many 5xx answers from a model within OVERLOAD_WINDOW seconds
# → it goes to the back of the chain for OVERLOAD_COOLDOWN seconds (the next player starts on a
# healthy model instead of waiting through the same retries).
OVERLOAD_STREAK, OVERLOAD_WINDOW, OVERLOAD_COOLDOWN = 3, 300, 180
_OVERLOAD_MARKERS = ("503", "500", "unavailable", "overloaded", "internal", "deadline")


class QuotaSkip(Exception):
    """Raised instead of calling a model whose free-tier budget is spent (try the next model)."""


# ── config ────────────────────────────────────────────────────────────────────
_TIER = contextvars.ContextVar("quest_google_tier", default=None)


def env_tier():
    """The configured tier of the main Google key: 'paid' (default — billing linked, Tier 1) or
    'free' (QUEST_GOOGLE_TIER=free)."""
    return "free" if os.environ.get("QUEST_GOOGLE_TIER", "paid").strip().lower() == "free" else "paid"


def tier_override():
    return _TIER.get()


def tier():
    """The tier in effect right now: a `use_tier()` override, else the configured one. Picks the
    limit table here and the prices in story_engine.estimate_cost."""
    return _TIER.get() or env_tier()


@contextlib.contextmanager
def use_tier(name):
    """Run a block on another tier — used to fall back to the free Google project once the
    monthly budget is spent. Free-tier counters are kept apart from paid ones ('free:<model>')."""
    token = _TIER.set(name)
    try:
        yield
    finally:
        _TIER.reset(token)


def _k(model):
    """State key: free-tier calls go to a different Google project, so they get own counters."""
    return f"free:{model}" if tier() == "free" else model


def limits():
    base = FREE_LIMITS if tier() == "free" else TIER1_LIMITS
    lim = {k: dict(v) for k, v in base.items()}
    extra = os.environ.get("QUEST_MODEL_LIMITS", "").strip()
    if extra:
        try:
            for k, v in json.loads(extra).items():
                lim[k] = {**lim.get(k, {}), **v}
        except (ValueError, AttributeError):
            pass
    return lim


def tracked(model):
    return model in limits()


def state_file():
    return os.environ.get("QUEST_QUOTA_FILE") or os.path.join("state", "quota.json")


def max_wait():
    try:
        return float(os.environ.get("QUEST_QUOTA_MAX_WAIT", "65"))
    except ValueError:
        return 65.0


def stories_per_player():
    try:
        return int(os.environ.get("QUEST_STORIES_PER_PLAYER", "3"))
    except ValueError:
        return 3


# ── Pacific-time day (quota resets at midnight Pacific) ───────────────────────
def _pacific_offset_hours(utc):
    """US Pacific offset without a tz database: PDT (−7) from the 2nd Sunday of March 10:00 UTC
    to the 1st Sunday of November 09:00 UTC, else PST (−8)."""
    y = utc.year
    march = datetime.datetime(y, 3, 8)
    dst_start = march + datetime.timedelta(days=(6 - march.weekday()) % 7, hours=10)
    nov = datetime.datetime(y, 11, 1)
    dst_end = nov + datetime.timedelta(days=(6 - nov.weekday()) % 7, hours=9)
    return -7 if dst_start <= utc.replace(tzinfo=None) < dst_end else -8


def pacific_now(now=None):
    ts = time.time() if now is None else now
    if PACIFIC is not None:
        return datetime.datetime.fromtimestamp(ts, PACIFIC)
    utc = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    return utc + datetime.timedelta(hours=_pacific_offset_hours(utc))


def quota_day(now=None):
    return pacific_now(now).strftime("%Y-%m-%d")


def seconds_until_reset(now=None):
    p = pacific_now(now)
    midnight = (p.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1))
    return max(0, int((midnight - p).total_seconds()))


def format_reset(now=None):
    s = seconds_until_reset(now)
    return f"{s // 3600} h {(s % 3600) // 60:02d} min"


# ── locked state file ─────────────────────────────────────────────────────────
@contextlib.contextmanager
def _state(now=None, write=True):
    path = state_file()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".lock", "a+") as lk:
        if fcntl:
            fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            day = quota_day(now)
            if data.get("day") != day:                   # new Pacific day → fresh counters
                data = {"day": day, "models": {}, "clients": {}, "runs": data.get("runs", [])}
            yield data
            if write:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=1)
                os.replace(tmp, path)
        finally:
            if fcntl:
                fcntl.flock(lk, fcntl.LOCK_UN)


def _model(data, model):
    return data["models"].setdefault(_k(model), {"rpd": 0, "minute": [], "tokens": [],
                                             "exhausted": False, "cooldown_until": 0, "why": ""})


# ── per-request gate ──────────────────────────────────────────────────────────
def estimate_tokens(system, messages):
    chars = len(system or "") + sum(len(m.get("content") or "") for m in messages or [])
    return chars // 4


def reserve(model, est_tokens=0, wait_limit=None, clock=time.time, sleep=time.sleep):
    """Ask to send ONE request to `model`. Returns (True, "") once the request is counted, or
    (False, reason) when this model should be skipped (day used up, or no per-minute slot within
    `wait_limit` seconds). Untracked models (e.g. Anthropic) always pass."""
    lim = limits().get(model)
    if not lim:
        return True, ""
    wait_limit = max_wait() if wait_limit is None else wait_limit
    waited = 0.0
    while True:
        t = clock()
        with _state(t) as d:
            m = _model(d, model)
            if m["exhausted"]:
                return False, f"{model}: free quota used up for today ({m.get('why') or 'daily limit'})"
            if m["rpd"] >= lim["rpd"]:
                m["exhausted"], m["why"] = True, f"{lim['rpd']}/day reached"
                return False, f"{model}: daily limit reached ({lim['rpd']}/day)"
            m["minute"] = [x for x in m["minute"] if t - x < 60]
            m["tokens"] = [p for p in m["tokens"] if t - p[0] < 60]
            wait = max(0.0, m.get("cooldown_until", 0) - t)
            if len(m["minute"]) >= lim["rpm"]:
                wait = max(wait, 60 - (t - min(m["minute"])) + 0.5)
            if lim.get("tpm") and m["tokens"] and sum(n for _, n in m["tokens"]) + est_tokens > lim["tpm"]:
                wait = max(wait, 60 - (t - min(x for x, _ in m["tokens"])) + 0.5)
            if wait <= 0:
                m["rpd"] += 1
                m["minute"].append(t)
                m["tokens"].append([t, int(est_tokens)])
                return True, ""
        if waited + wait > wait_limit:
            return False, f"{model}: per-minute limit busy"
        sleep(wait)
        waited += wait


def note_error(model, message, clock=time.time):
    """Learn from a failed call: daily quota → off until reset; per-minute → 60 s cool-down;
    unknown/unsupported model → off for the day."""
    if not tracked(model):
        return
    msg = (message or "").lower()
    t = clock()
    with _state(t) as d:
        m = _model(d, model)
        if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
            if "per day" in msg or "perday" in msg or "daily" in msg or "requestsperday" in msg:
                m["exhausted"], m["why"] = True, "API said daily quota exceeded"
            else:
                m["cooldown_until"] = t + 60
        elif "404" in msg or "not found" in msg or "not supported" in msg:
            m["exhausted"], m["why"] = True, "model not available to this key"
        elif is_overload(msg):                           # Google-side 5xx: remember the streak
            o = [x for x in m.get("overloads", []) if t - x < OVERLOAD_WINDOW] + [t]
            m["overloads"] = o[-10:]
            if len(o) >= OVERLOAD_STREAK:
                m["overloaded_until"] = t + OVERLOAD_COOLDOWN


def is_overload(message):
    """A temporary server-side error (503 overloaded, 500 internal, timeout) — worth retrying."""
    msg = (message or "").lower()
    return any(k in msg for k in _OVERLOAD_MARKERS)


def note_success(model):
    """A call went through — clear the model's overload streak."""
    if not tracked(model):
        return
    with _state() as d:
        m = _model(d, model)
        if m.get("overloads") or m.get("overloaded_until"):
            m["overloads"], m["overloaded_until"] = [], 0


def overloaded(model, now=None):
    t = time.time() if now is None else now
    with _state(t, write=False) as d:
        return d["models"].get(_k(model), {}).get("overloaded_until", 0) > t


def healthy_first(models, now=None):
    """Same chain, but models that are overloaded right now move to the back (still tried if
    everything else fails)."""
    t = time.time() if now is None else now
    with _state(t, write=False) as d:
        bad = {m for m in models if d["models"].get(_k(m), {}).get("overloaded_until", 0) > t}
    return [m for m in models if m not in bad] + [m for m in models if m in bad]


# ── capacity / stats ──────────────────────────────────────────────────────────
def record_run(writer_calls, review_calls, cost_usd=0.0):
    """Remember how many calls (and dollars) one generation run took (feeds the averages)."""
    with _state() as d:
        run = [int(writer_calls), int(review_calls), round(float(cost_usd or 0.0), 6)]
        d["runs"] = (d.get("runs", []) + [run])[-30:]


def averages():
    with _state(write=False) as d:
        runs = d.get("runs", [])
    if len(runs) < 3:
        return DEFAULT_AVG_WRITER_CALLS, DEFAULT_AVG_REVIEW_CALLS
    return (max(1.0, sum(r[0] for r in runs) / len(runs)),
            max(0.0, sum(r[1] for r in runs) / len(runs)))


def average_cost():
    """Average USD per generation run, measured on paid runs (default until 3 are recorded)."""
    with _state(write=False) as d:
        costs = [r[2] for r in d.get("runs", []) if len(r) > 2 and r[2] > 0]
    return sum(costs) / len(costs) if len(costs) >= 3 else DEFAULT_AVG_COST_USD


def remaining(models, now=None):
    """Requests still available today across `models` (tracked ones only)."""
    lim = limits()
    with _state(now, write=False) as d:
        left = 0
        for model in models:
            if model not in lim:
                continue
            m = d["models"].get(_k(model), {})
            if not m.get("exhausted"):
                left += max(0, lim[model]["rpd"] - m.get("rpd", 0))
    return left


def capacity(writer_models, review_models=(), now=None, budget_left=None):
    """≈ how many more stories can be generated: today's request limits, and — when
    `budget_left` (USD left this month) is given — what the remaining budget pays for.
    `limited_by` says which one binds: "quota" (resets at midnight Pacific) or "budget"."""
    aw, ar = averages()
    wl, rl = remaining(writer_models, now), remaining(review_models, now)
    by_quota = int(math.floor(wl / aw)) if aw else 0
    avg_cost = average_cost()
    stories, limited_by = by_quota, "quota"
    if budget_left is not None:
        by_budget = int(math.floor(max(0.0, budget_left) / avg_cost + 1e-9)) if avg_cost > 0 else by_quota
        if by_budget < by_quota:
            stories, limited_by = by_budget, "budget"
    return {"stories": stories, "limited_by": limited_by, "writer_left": wl, "review_left": rl,
            "avg_writer": round(aw, 1), "avg_review": round(ar, 1), "avg_cost": round(avg_cost, 4),
            "tier": tier(), "resets_in": seconds_until_reset(now), "resets_in_text": format_reset(now)}


def client_used(client_id, now=None):
    with _state(now, write=False) as d:
        return int(d.get("clients", {}).get(str(client_id), 0))


def record_client(client_id, now=None):
    with _state(now) as d:
        c = d.setdefault("clients", {})
        c[str(client_id)] = int(c.get(str(client_id), 0)) + 1
        if len(c) > 5000:                                # keep the file small
            for k in list(c)[:1000]:
                del c[k]


def usage(now=None):
    lim = limits()
    with _state(now, write=False) as d:
        return {k: {"used": d["models"].get(_k(k), {}).get("rpd", 0), "limit": v["rpd"],
                    "rpm": v["rpm"], "exhausted": d["models"].get(_k(k), {}).get("exhausted", False),
                    "why": d["models"].get(_k(k), {}).get("why", "")} for k, v in lim.items()}


# ── one generation at a time ──────────────────────────────────────────────────
@contextlib.contextmanager
def generation_slot(timeout=120.0, poll=1.0):
    """Exclusive story-generation slot across threads AND processes. Yields True when acquired,
    False if another generation still holds it after `timeout` seconds."""
    path = os.path.join(os.path.dirname(state_file()) or ".", "generate.lock")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fh = open(path, "a+")
    got = False
    try:
        deadline = time.time() + timeout
        while fcntl:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.time() >= deadline:
                    break
                time.sleep(poll)
        if not fcntl:
            got = True
        yield got
    finally:
        if got and fcntl:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import story_engine as E
    writer, reviewer = E.gen_models("google"), E.review_models("google")
    if "--check-models" in argv or "check-models" in argv:   # flag or plain word (some docker
                                                            # compose versions eat --flags)
        from google import genai
        names = {m.name.split("/")[-1] for m in genai.Client(api_key=E.env_api_key("google")).models.list()}
        for role, chain in (("writer", writer), ("reviewer", reviewer)):
            for m in chain:
                print(f"  {'✓' if m in names else '✗ NOT AVAILABLE'}  {role:8s} {m}")
        return
    budget_left = E.budget_left()
    cap = capacity(writer, reviewer, budget_left=budget_left)
    u = usage()
    print(f"Gemini {tier()} tier — today (Pacific {quota_day()}), resets in {cap['resets_in_text']}")
    for role, chain in (("writer", writer), ("reviewer", reviewer)):
        for m in chain:
            if m in u:
                x = u[m]
                flag = f"  OFF: {x['why']}" if x["exhausted"] else ""
                flag += "  (overloaded — tried last for now)" if overloaded(m) else ""
                print(f"  {role:8s} {m:24s} {x['used']:>5}/{x['limit']:<6} today  ({x['rpm']}/min){flag}")
    print(f"\n  writer calls left {cap['writer_left']} · review calls left {cap['review_left']} · "
          f"avg per story {cap['avg_writer']} + {cap['avg_review']} calls, ≈ {E.money(cap['avg_cost'], 3)}")
    if budget_left is not None:
        print(f"  monthly budget: {E.money(E.month_spend())} of {E.money(E.monthly_budget())} spent")
    when = "this month (budget)" if cap["limited_by"] == "budget" else "today"
    print(f"  ≈ {cap['stories']} more stor{'y' if cap['stories'] == 1 else 'ies'} can be created {when}")
    if tier() == "paid" and E.free_google_key():
        with use_tier("free"):
            fcap = capacity(E.free_fallback_models(), reviewer)
        print(f"  free backup project (after the budget): ≈ {fcap['stories']} stories left today")


if __name__ == "__main__":
    main(sys.argv)
