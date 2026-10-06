"""
story_engine.py — Streamlit-free core for generating and vetting Quest Book stories.

Shared by:
  - app.py          → the in-app "Create a New Story" page
  - story_agent.py  → the standalone CLI orchestrator (runs on any server, free Gemini key)

This module has NO Streamlit dependency, so the agent can run with only `google-genai`
installed (no need for streamlit on a generation-only server). It holds:
  - provider config (Google Gemini by default; Anthropic optional)
  - the spec/system prompt + user prompt builders
  - the model call (with retry/backoff) and JSON extraction
  - correctness validation (reuses cyoa-validator) and the balance gate (runs playtest.py)
  - story library IO helpers

Run from the repository root (paths below are repo-relative).
"""
import os
import re
import json
import time
import random
import glob
import tempfile
import subprocess

import game_rules as R   # shared challenge rules (dead-end counts per difficulty, ...)
import narrative_review as NR   # the story-review agent (4th gate: continuity)
import quota as Q               # free-tier rate limits: per-model RPM/TPM/RPD tracking
from functools import lru_cache

def _load_dotenv(path=".env"):
    """Minimal .env loader (no dependency) so the CLI works outside docker-compose.
    Reads KEY=VALUE lines (also `export KEY=VALUE`); never overrides variables that
    are already set in the environment."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv()

# ── config ─────────────────────────────────────────────────────────────────────
STORIES_DIR    = os.environ.get("QUEST_STORIES_DIR", "stories")
VALIDATOR_PATH = os.path.join("cyoa-skills", "cyoa-validator", "scripts", "validate_story.py")
COHERENCE_PATH = os.path.join("cyoa-skills", "cyoa-validator", "scripts", "coherence_report.py")
PLAYTEST_PATH  = "playtest.py"
GENERATOR_SPEC = os.path.join("cyoa-skills", "cyoa-generator", "SKILL.md")
DIFFICULTIES   = ["easy", "normal", "hard"]
GEN_MAX_TOKENS = 16000

DEFAULT_MODELS = {"google": "gemini-3.8-flash", "anthropic": "claude-sonnet-4-6"}
# Fallback chains: if a model hits its (free-tier) limit, the agent advances to the next one.
# Override with QUEST_GEN_MODELS="m1,m2,..." or pin a single one with QUEST_GEN_MODEL="m".
# Google: Flash models only (Pro would cost several times more). On the free tier each has
# its own 20 requests/day, so writing rotates through all of them; on Tier 1 the chain is
# mostly a fallback for Google-side overload (503). Reviewing uses the Flash Lite models.
DEFAULT_MODEL_CHAINS = {
    "google":    ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
                  "gemini-3.5-flash", "gemini-2.5-flash"],
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
}
PROVIDER_LABEL = {"google": "Google (Gemini)", "anthropic": "Anthropic (Claude)"}
PROVIDER_PKG   = {"google": "google-genai", "anthropic": "anthropic"}

# ── cost tracking & monthly budget ──────────────────────────────────────────────
# Paid API prices in USD per 1,000,000 tokens (input, output) — AI Studio, 2026-10-06.
# EDIT THIS TABLE if prices change or you add models (unknown models count as $0!).
# With QUEST_GOOGLE_TIER=free every Gemini call counts as $0 instead.
MODEL_PRICING = {
    "claude-opus-4-8":           (5.0, 25.0),
    "claude-sonnet-4-6":         (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0,  5.0),
    "gemini-3.8-flash":          (0.75, 3.75),  # 3.8/3.7/3.6: price doubles on 2027-01-01
    "gemini-3.7-flash":          (0.75, 3.75),  #   (→ 1.50 / 7.50) — update then
    "gemini-3.6-flash":          (0.75, 3.75),
    "gemini-3.5-flash":          (1.5,  9.0),
    "gemini-2.5-flash":          (0.30, 2.50),
    "gemini-3.1-pro":            (2.0, 12.0),
    "gemini-3.5-flash-lite":     (0.30, 2.50),
    "gemini-3.1-flash-lite":     (0.25, 1.50),
    "gemini-2.5-flash-lite":     (0.10, 0.40),
}


def google_tier():
    """'paid' (default — billing linked, Tier 1) or 'free' (QUEST_GOOGLE_TIER=free).
    On the free tier every Gemini call costs $0, so the budget ledger counts nothing for it."""
    return Q.tier()


def estimate_cost(model, input_tokens, output_tokens):
    """Estimated USD cost of one call. Unknown models — and Gemini on the free tier — are $0."""
    if str(model).startswith("gemini") and google_tier() == "free":
        return 0.0
    pin, pout = MODEL_PRICING.get(model, (0.0, 0.0))
    return (int(input_tokens or 0) / 1_000_000) * pin + (int(output_tokens or 0) / 1_000_000) * pout


# ── budget currency ───────────────────────────────────────────────────────────
# Model prices (and the ledger) are in USD. The budget can be set and shown in the currency you
# are billed in: QUEST_BUDGET_CURRENCY=SEK + QUEST_USD_RATE=<SEK per 1 USD> (put VAT in the rate,
# e.g. 10.07 × 1.25, if your bill includes it) + QUEST_MONTHLY_BUDGET=<amount in SEK>.
_CURRENCY_FMT = {"USD": "${:.2f}", "SEK": "{:.2f} kr", "EUR": "€{:.2f}", "GBP": "£{:.2f}",
                 "NOK": "{:.2f} kr", "DKK": "{:.2f} kr"}


def budget_currency():
    return (os.environ.get("QUEST_BUDGET_CURRENCY", "USD").strip().upper() or "USD")


def usd_rate():
    """Units of the budget currency per 1 USD (1.0 for USD)."""
    if budget_currency() == "USD":
        return 1.0
    try:
        r = float(os.environ.get("QUEST_USD_RATE", "") or 0)
    except ValueError:
        r = 0.0
    return r if r > 0 else 1.0


def money(usd, digits=2):
    """Format a USD amount in the budget currency, e.g. money(1.5) → '15.11 kr'."""
    cur = budget_currency()
    v = float(usd or 0) * usd_rate()
    fmt = _CURRENCY_FMT.get(cur, "{:.2f} " + cur)
    return fmt.replace(":.2f", f":.{digits}f").format(v)


# Monthly spend cap. 0 / unset (default) = unlimited, feature OFF. Set QUEST_MONTHLY_BUDGET in
# the budget currency (or the older QUEST_MONTHLY_BUDGET_USD in dollars). Returned in USD, the
# ledger's unit. When this month's spend reaches it, creation switches to the free tier (with a
# separate free key, see budget_fallback_models) or pauses.
def monthly_budget():
    raw = os.environ.get("QUEST_MONTHLY_BUDGET", "").strip()
    try:
        if raw:
            return float(raw) / usd_rate()
        return float(os.environ.get("QUEST_MONTHLY_BUDGET_USD", "0") or 0)
    except ValueError:
        return 0.0


def free_google_key():
    """API key of a Google project WITHOUT billing (the free tier). Billing is per project, so
    the paid key can't fall back to free — a second project's key is needed for that."""
    key = os.environ.get("QUEST_GOOGLE_FREE_API_KEY", "").strip()
    if not key and Q.env_tier() == "free":           # the main key is already a free one
        key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    return key


def free_fallback_models():
    """The free Google model chain used once the monthly paid budget is exhausted: every Flash
    model in rotation (20 requests/day each on the free tier)."""
    chain = os.environ.get("QUEST_FREE_FALLBACK_MODELS", "").strip()
    if chain:
        return [m.strip() for m in chain.split(",") if m.strip()]
    return list(DEFAULT_MODEL_CHAINS["google"])


USAGE_FILE = os.environ.get("QUEST_USAGE_FILE", os.path.join("state", "usage.json"))


def _load_usage():
    try:
        with open(USAGE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _month_key(when=None):
    return time.strftime("%Y-%m", time.gmtime(when))


def month_spend(when=None):
    """USD spent so far in the given (default current) calendar month."""
    return float(_load_usage().get(_month_key(when), {}).get("cost_usd", 0.0))


def record_spend(cost, model="", tokens_in=0, tokens_out=0, when=None):
    """Add one generation's cost to the month's running total. Never raises — cost
    tracking must not be able to break story generation."""
    if not cost:
        cost = 0.0
    try:
        data = _load_usage()
        mk = _month_key(when)
        m = data.setdefault(mk, {"cost_usd": 0.0, "stories": 0, "tokens_in": 0, "tokens_out": 0})
        m["cost_usd"]   = round(m.get("cost_usd", 0.0) + float(cost), 6)
        m["stories"]    = m.get("stories", 0) + 1
        m["tokens_in"]  = m.get("tokens_in", 0) + int(tokens_in or 0)
        m["tokens_out"] = m.get("tokens_out", 0) + int(tokens_out or 0)
        os.makedirs(os.path.dirname(USAGE_FILE) or ".", exist_ok=True)
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def budget_exceeded():
    """True only if a cap is set (>0) AND this month's spend has reached it."""
    cap = monthly_budget()
    return cap > 0 and month_spend() >= cap


def budget_left():
    """USD left in this month's budget, or None when no cap is set."""
    cap = monthly_budget()
    return max(0.0, cap - month_spend()) if cap > 0 else None


def budget_fallback_models():
    """What generation may still use once the monthly budget is spent: the free Google chain
    when a free-tier key exists (QUEST_GOOGLE_FREE_API_KEY, or the main key on the free tier).
    With only a paid key → [] : creation pauses until next month, the library stays playable.
    Run the fallback inside `free_tier()` so limits, prices and the key all switch to free."""
    return free_fallback_models() if free_google_key() else []


def free_tier():
    """Context manager: everything inside runs on the free Google project — free-tier limits,
    $0 prices, and env_api_key('google') returns the free key (also for the story review)."""
    return Q.use_tier("free")


def gen_provider():
    """Pick the model provider from env (QUEST_GEN_PROVIDER), else whichever API key is set."""
    p = os.environ.get("QUEST_GEN_PROVIDER", "").strip().lower()
    if p in ("google", "gemini"):
        return "google"
    if p in ("anthropic", "claude"):
        return "anthropic"
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "google"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "google"


def gen_default_model(provider):
    return os.environ.get("QUEST_GEN_MODEL") or DEFAULT_MODELS.get(provider, "")


def gen_models(provider):
    """Ordered fallback chain of models to try for this provider.
    QUEST_GEN_MODELS='m1,m2,...' overrides the chain; QUEST_GEN_MODEL='m' pins a single model."""
    chain = os.environ.get("QUEST_GEN_MODELS", "").strip()
    if chain:
        return [m.strip() for m in chain.split(",") if m.strip()]
    single = os.environ.get("QUEST_GEN_MODEL", "").strip()
    if single:
        return [single]
    return list(DEFAULT_MODEL_CHAINS.get(provider, [DEFAULT_MODELS.get(provider, "")]))


def env_api_key(provider):
    if provider == "google":
        if Q.tier_override() == "free":             # inside free_tier(): the free project's key
            return free_google_key()
        return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    return os.environ.get("ANTHROPIC_API_KEY") or ""


# ── story library IO ─────────────────────────────────────────────────────────
def list_stories():
    """Metadata for every story in the library (stories/*.json)."""
    paths = sorted(p for p in glob.glob(os.path.join(STORIES_DIR, "*.json"))
                   if not os.path.basename(p).startswith((".", "_")))
    out = []
    for p in paths:
        try:
            d = json.load(open(p))
            out.append({
                "path": p,
                "title": d.get("title", os.path.basename(p)),
                "theme": d.get("theme", ""),
                "difficulty": (d.get("difficulty") or "").lower(),
                "goal": d.get("goal", ""),
                "n": len(d.get("locations", {})),
                "draft": bool(d.get("draft")),
                "language": d.get("language", ""),
                "language_level": d.get("language_level", ""),
            })
        except Exception as e:
            out.append({"path": p, "title": os.path.basename(p), "error": str(e),
                        "theme": "", "difficulty": "", "goal": "", "n": 0, "draft": False,
                        "language": "", "language_level": ""})
    return out


def load_story_file(path):
    with open(path, "r") as f:
        return json.load(f)


def slugify(s):
    # \w keeps Unicode letters/digits, so non-Latin titles (e.g. Russian) get real slugs
    # instead of collapsing to the "story" fallback
    s = re.sub(r"[^\w]+", "_", (s or "").lower()).strip("_")
    return s[:40] or "story"


def unique_story_path(title):
    os.makedirs(STORIES_DIR, exist_ok=True)
    base = slugify(title)
    path = os.path.join(STORIES_DIR, base + ".json")
    i = 2
    while os.path.exists(path):
        path = os.path.join(STORIES_DIR, f"{base}_{i}.json")
        i += 1
    return path


def save_story_file(story, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(story, f, indent=2, ensure_ascii=False)


# Git auto-push of stories was removed (deprecated): stories live on the server in stories/
# and are backed up to S3 (below). Player-generated content no longer goes into the public repo,
# and the server no longer needs a GitHub write token.


# ── optional S3-compatible story storage (AWS S3 / Cloudflare R2 / Backblaze B2 / MinIO) ──
# Enable by setting QUEST_S3_BUCKET. The bucket is the durable, cross-machine store; the
# local stories/ folder acts as a cache: new stories are uploaded on save, and the app
# pulls missing/newer stories down at startup. Credentials use the standard AWS env vars
# (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) or any boto3 credential source.
#   QUEST_S3_BUCKET    bucket name (setting this turns the feature on)
#   QUEST_S3_ENDPOINT  custom endpoint for R2/B2/MinIO, e.g. https://<acct>.r2.cloudflarestorage.com
#   QUEST_S3_REGION    region (optional; e.g. "auto" for R2)
#   QUEST_S3_PREFIX    key prefix inside the bucket (default "stories/")

def s3_enabled():
    return bool(os.environ.get("QUEST_S3_BUCKET"))


@lru_cache(maxsize=1)
def _s3_client():
    import boto3   # lazy: only needed when QUEST_S3_BUCKET is set
    kw = {}
    if os.environ.get("QUEST_S3_ENDPOINT"):
        kw["endpoint_url"] = os.environ["QUEST_S3_ENDPOINT"]
    if os.environ.get("QUEST_S3_REGION"):
        kw["region_name"] = os.environ["QUEST_S3_REGION"]
    return boto3.client("s3", **kw)


def _s3_conf():
    return (os.environ.get("QUEST_S3_BUCKET", ""),
            os.environ.get("QUEST_S3_PREFIX", "stories/").strip("/") + "/")


def push_story_to_s3(path, client=None):
    """Upload one story file to the bucket. Returns (ok, detail); never raises."""
    if not s3_enabled():
        return False, "S3 storage not configured (set QUEST_S3_BUCKET)"
    bucket, prefix = _s3_conf()
    key = prefix + os.path.basename(path)
    try:
        client = client or _s3_client()
        client.upload_file(path, bucket, key, ExtraArgs={"ContentType": "application/json"})
        return True, f"uploaded to s3://{bucket}/{key}"
    except ImportError:
        return False, "boto3 isn't installed — pip install boto3"
    except Exception as e:
        return False, f"S3 upload failed: {str(e)[:300]}"


def sync_stories_from_s3(client=None):
    """Download stories that exist in the bucket but are missing (or newer) locally.
    Returns (n_downloaded, errors); never raises. The bucket wins on conflicts."""
    if not s3_enabled():
        return 0, []
    bucket, prefix = _s3_conf()
    n, errors = 0, []
    try:
        client = client or _s3_client()
        os.makedirs(STORIES_DIR, exist_ok=True)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                name = os.path.basename(obj["Key"])
                if not name.endswith(".json"):
                    continue
                local = os.path.join(STORIES_DIR, name)
                if (not os.path.exists(local)
                        or obj["LastModified"].timestamp() > os.path.getmtime(local) + 1):
                    try:
                        client.download_file(bucket, obj["Key"], local)
                        n += 1
                    except Exception as e:
                        errors.append(f"{name}: {str(e)[:200]}")
    except ImportError:
        errors.append("boto3 isn't installed — pip install boto3")
    except Exception as e:
        errors.append(f"S3 sync failed: {str(e)[:300]}")
    return n, errors


def seed_s3_from_local(client=None):
    """One-time migration helper: upload every local story the bucket doesn't have yet.
    Returns (n_uploaded, errors); never raises."""
    if not s3_enabled():
        return 0, ["S3 storage not configured (set QUEST_S3_BUCKET)"]
    bucket, prefix = _s3_conf()
    n, errors = 0, []
    try:
        client = client or _s3_client()
        have = set()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            have |= {os.path.basename(o["Key"]) for o in page.get("Contents", [])}
        for p in glob.glob(os.path.join(STORIES_DIR, "*.json")):
            if os.path.basename(p) not in have:
                ok, detail = push_story_to_s3(p, client=client)
                if ok:
                    n += 1
                else:
                    errors.append(detail)
    except ImportError:
        errors.append("boto3 isn't installed — pip install boto3")
    except Exception as e:
        errors.append(f"S3 seed failed: {str(e)[:300]}")
    return n, errors


# ── gates: correctness + balance ───────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_validator():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cyoa_validator", VALIDATOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_story_dict(story):
    """Return a list of human-readable problems. Empty list == valid & complete."""
    if not isinstance(story, dict):
        return ["story is not a JSON object"]
    problems = [f"missing required field '{f}'"
                for f in ("title", "character_template", "start_location_id", "locations")
                if f not in story]
    if problems:
        return problems
    locs = story.get("locations") or {}
    if story["start_location_id"] not in locs:
        return [f"start_location_id '{story['start_location_id']}' is not a location"]
    try:
        _reach, issues = _load_validator().simulate(story)
        problems += [it["message"] for it in issues]
    except Exception as e:
        problems.append(f"validator crashed on this story: {e}")
    return problems


def _run(cmd, timeout=200):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def coherence_check(path):
    """Run coherence_report.py. Returns (ok_bool, [REVIEW item lines])."""
    try:
        r = _run(["python3", COHERENCE_PATH, path])
        out = r.stdout
        ok = "COHERENCE: OK" in out
        review = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[")]
        return ok, review
    except Exception as e:
        return False, [f"(coherence check failed to run: {e})"]


def balance_check(path, difficulty):
    """Run playtest.py as a balance gate. Returns (verdict, [metric/hint lines])."""
    try:
        r = _run(["python3", PLAYTEST_PATH, path, difficulty])
        out = r.stdout
        verdict = "PASS" if ">>> PASS" in out else ("ADJUST" if "ADJUST" in out else "—")
        lines = [ln.strip() for ln in out.splitlines()
                 if ln.strip().startswith(("cautious win", "heroic death", "hint:"))]
        return verdict, lines
    except Exception as e:
        return "—", [f"(balance check unavailable: {e})"]


# ── model access ────────────────────────────────────────────────────────────────
def extract_json(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b == -1 or b < a:
        return None, "no JSON object found in the model output"
    try:
        return json.loads(t[a:b + 1]), None
    except Exception as e:
        return None, f"JSON parse error: {e}"


def call_model(provider, model, system, messages, api_key, usage_sink=None):
    """One completion from the chosen provider. messages: [{'role':'user'|'assistant','content'}].
    Returns the model's text. Raises ImportError if the provider SDK isn't installed.
    Server overload (503 / 500 / timeout) is retried PATIENTLY with jittered backoff
    (≈5 → 10 → 20 → 30 s) for up to `overload_patience()` seconds before giving up on this model,
    so the best model gets a fair chance before call_with_fallback steps down the chain.
    If `usage_sink` is a list, appends {model, input_tokens, output_tokens, cost_usd} per call."""
    retryable = ("503", "500", "429", "UNAVAILABLE", "INTERNAL", "RESOURCE_EXHAUSTED",
                 "rate_limit", "overloaded", "DEADLINE")
    patience = overload_patience()
    waited, delay, attempt = 0.0, 5.0, 0

    def _record(tin, tout):
        if usage_sink is not None:
            usage_sink.append({"model": model, "input_tokens": int(tin or 0),
                               "output_tokens": int(tout or 0),
                               "cost_usd": estimate_cost(model, tin, tout)})

    while True:
        attempt += 1
        if Q.tracked(model):                     # free-tier budget: count it, wait, or skip
            ok, why = Q.reserve(model, Q.estimate_tokens(system, messages))
            if not ok:
                raise Q.QuotaSkip(why)
        try:
            if provider == "anthropic":
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model=model, max_tokens=GEN_MAX_TOKENS, system=system,
                    messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                )
                u = getattr(msg, "usage", None)
                _record(getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
                Q.note_success(model)
                return "".join(getattr(b, "text", "") for b in msg.content
                               if getattr(b, "type", "") == "text")
            # default: Google Gemini
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            contents = [types.Content(role=("model" if m["role"] == "assistant" else "user"),
                                      parts=[types.Part(text=m["content"])]) for m in messages]
            cfg = dict(system_instruction=system, max_output_tokens=GEN_MAX_TOKENS,
                       temperature=0.9, response_mime_type="application/json")
            afc = getattr(types, "AutomaticFunctionCallingConfig", None)
            if afc is not None:      # we pass no tools — turn AFC off (silences the SDK's AFC warning)
                cfg["automatic_function_calling"] = afc(disable=True)
            resp = client.models.generate_content(
                model=model, contents=contents, config=types.GenerateContentConfig(**cfg))
            um = getattr(resp, "usage_metadata", None)
            _record(getattr(um, "prompt_token_count", 0), getattr(um, "candidates_token_count", 0))
            Q.note_success(model)
            return resp.text or ""
        except Exception as e:
            err = str(e)
            if Q.tracked(model):
                Q.note_error(model, err)         # learn daily / per-minute limits, overload, 404s
                if any(k in err for k in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND")):
                    raise                        # don't burn more quota retrying — next model
            if not any(k in err for k in retryable):
                raise                            # a real error (bad request, auth…) — no retry
            if Q.is_overload(err):
                pause = min(delay, 30.0) * random.uniform(0.8, 1.2)
                if waited + pause > patience:
                    raise                        # patience used up — next model in the chain
                delay *= 2
            else:                                # untracked model's rate limit: 2 quick retries
                if attempt > 2:
                    raise
                pause = 4.0 * attempt
            _sleep(pause)
            waited += pause


def overload_patience():
    """Seconds one model may spend waiting out 503/500 answers before the chain steps down.
    Default 60 (a player is watching); scripts set QUEST_OVERLOAD_PATIENCE higher."""
    try:
        return max(0.0, float(os.environ.get("QUEST_OVERLOAD_PATIENCE", "60")))
    except ValueError:
        return 60.0


def _sleep(seconds):                             # indirection so tests can skip real waiting
    time.sleep(seconds)


def call_with_fallback(provider, models, system, messages, api_key, log=None, usage_sink=None):
    """Try each model in order; on ANY failure advance to the next one. This is what makes the
    agent survive free-tier limits: when a model's quota is exhausted (or it's unavailable), the
    next model in the chain takes over — models whose free-tier day is already used up are
    skipped without a call (quota.py), and models Google is currently overloaded on are tried
    last. Returns (text, model_used); raises only if all fail."""
    errors, skipped = [], 0
    models = Q.healthy_first(list(models))
    for i, model in enumerate(models):
        try:
            return call_model(provider, model, system, messages, api_key, usage_sink=usage_sink), model
        except Exception as e:
            skipped += isinstance(e, Q.QuotaSkip)
            errors.append(f"{model}: {str(e)[:200]}")
            if i < len(models) - 1:
                if log:
                    log(f"    ! {model} unavailable ({str(e)[:70]}…) — switching to {models[i + 1]}")
                continue
            if skipped == len(models):
                raise RuntimeError(f"the daily request quota is used up on every model "
                                   f"({', '.join(models)}); it resets in {Q.format_reset()}") from e
            raise RuntimeError("all configured models failed:\n  " + "\n  ".join(errors)) from e
    raise RuntimeError("no models configured")


CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _language_clause(language, language_level):
    """Prompt fragment enforcing the story language and CEFR level."""
    language = (language or "English").strip() or "English"
    level = (language_level or "C2").strip().upper()
    if level not in CEFR_LEVELS:
        level = "C2"
    style = {
        "A1": "very short, simple sentences (max ~8 words), present tense only, only the most "
              "common everyday words, repeat key words instead of using synonyms",
        "A2": "short, simple sentences, mostly present tense, high-frequency vocabulary, "
              "no idioms or rare words",
        "B1": "clear everyday narrative, moderate sentence length, common idioms only",
        "B2": "natural fluent narrative, varied sentence structure, everyday idioms allowed",
        "C1": "rich, nuanced prose with idiom and atmosphere",
        "C2": "full native richness — idiom, subtext, and atmosphere",
    }[level]
    return (
        f'Language: write ALL player-facing text (title, goal, prologue, location descriptions, '
        f'choice texts, item names and descriptions, monster names) in {language} at CEFR level '
        f'{level}: {style}. Keep JSON keys, location ids and item ids in English snake_case. '
        f'Set the top-level fields "language": "{language}" and "language_level": "{level}".\n'
    )


def build_prompts(theme, difficulty, length, title_hint="", language="English", language_level="C2"):
    """Return (system, user) prompts. The spec file is the authoritative system prompt."""
    spec = open(GENERATOR_SPEC).read() if os.path.exists(GENERATOR_SPEC) else ""
    system = (
        "You are the story generator for the Quest Book CYOA engine. Return exactly ONE "
        "story as a single JSON object that conforms to the specification below. Output "
        "ONLY the JSON object — no prose, no markdown, no code fences.\n\n"
        "=== SPECIFICATION ===\n" + spec
    )
    lo, hi = R.trap_band(difficulty, length)
    if hi == 0:
        endings = "3-5 endings (they can all be victories of different kinds)"
        dead_ends = ("DEAD ENDS: none — this is an easy story. Every location must still be able to "
                     "reach a victory, and no choice may carry trap_hint.\n")
    else:
        want = f"exactly {lo}" if lo == hi else f"{lo}-{hi}"
        endings = "3-5 endings, including the non-victory endings of the dead-end branches"
        dead_ends = (
            f"DEAD ENDS: include {want} hinted dead-end branch(es). Each starts with a choice that "
            f'carries "trap_hint": a phrase copied VERBATIM from that location\'s description which '
            f"foreshadows the danger; the branch is played out over 2-3 locations and ends in an "
            f"is_victory:false ending, and nothing in it leads back to a victory. Apart from these, "
            f"every location must be able to reach a victory, and no ordinary choice may jump "
            f"straight to a bad ending.\n")
    stakes = {"easy": "3-5", "normal": "5-7", "hard": "7-9"}.get((difficulty or "").lower(), "5-7")
    user = (
        f"Theme: {theme}\n"
        f"Difficulty: {difficulty}\n"
        f"Target size: about {length} locations, with {endings}.\n"
        + (f'Preferred title: "{title_hint}"\n' if title_hint else "")
        + _language_clause(language, language_level)
        + f'Set the top-level "difficulty" field to "{difficulty}" and tune health, check DCs, '
          f"fail_damage and monsters to the {difficulty} preset in the spec.\n"
        + "Write a 'prologue' (3-6 sentences of pre-history: who the player is, the world, the "
          "inciting incident, and the stakes). Design a COHERENT, connected map — regions that "
          "link logically, no random teleports, no set of rooms the player can circle at zero "
          "cost, and most choices moving the story FORWARD. Every location must be reachable and "
          "able to reach an ending; no dead items.\n"
        + "CHALLENGES: every check and monster is resolved by ONE roll and is always passable — on "
          "a failure the hero still continues to the same destination but loses fail_damage HP. "
          "Never use fail_target. Give EVERY condition and EVERY monster a success_text and a "
          "realistic fail_text (in the story language) describing the injury that matches the "
          "approach — forcing a door hurts a shoulder, squeezing through a splintered gap cuts an "
          "arm, outlasting something leaves you exhausted. Offer different approaches to an "
          "obstacle as separate choices with different attributes. Every monster location needs at "
          "least one non-flee onward choice.\n"
        + f"STAKES: every route from the start to a victory must pass through {stakes} challenges "
          f"(checks or monsters); free choices must not let a careful player bypass all the danger.\n"
        + dead_ends
        + "BRANCHING: most non-ending locations need 2-3 meaningful choices; never chain more "
          "than 2-3 single-choice locations in a row (a corridor fails the coherence gate).\n"
        + "ITEMS: every item must be introduced in the narrative — mention the object in the "
          "granting location's description or grant it via an explicit pick-up choice "
          "(gives_item). Items must never appear out of nowhere, and the same item must not be "
          "collectable twice on one path."
    )
    return system, user


def generate_story_api(theme, difficulty, length, title_hint, api_key, provider, model,
                       language="English", language_level="C2"):
    """Author a story via the chosen provider; validate + repair (correctness only) up to 3 times.
    Returns (story_or_None, problems_list) — problems empty == passes correctness.
    (The CLI agent in story_agent.py wraps this with the coherence + balance gates too.)"""
    system, user = build_prompts(theme, difficulty, length, title_hint, language, language_level)
    messages = [{"role": "user", "content": user}]
    story, problems = None, ["no output produced"]
    for _ in range(3):
        text = call_model(provider, model, system, messages, api_key)
        story, perr = extract_json(text)
        if story is None:
            messages += [{"role": "assistant", "content": text or ""},
                         {"role": "user", "content": f"{perr}. Resend ONLY the corrected, complete JSON object."}]
            problems = [perr]
            continue
        problems = validate_story_dict(story)
        if not problems:
            return story, []
        messages += [{"role": "assistant", "content": json.dumps(story)},
                     {"role": "user", "content": "The story failed validation. Fix ALL of these and "
                      "resend ONLY the full corrected JSON:\n- " + "\n- ".join(problems[:25])}]
    return story, problems


# ── the full gated pipeline (shared by the app's Create page AND story_agent.py) ──
# ── 4th gate: the story-review agent (narrative_review.py) ────────────────────
# A cheap model reads the whole story and flags continuity problems. It runs only after the
# three free gates pass, so no money is spent reviewing a structurally broken draft.
#   QUEST_REVIEW=0                     turn the review gate off
#   QUEST_REVIEW_PROVIDER              google | anthropic (default: the generation provider)
#   QUEST_REVIEW_MODELS="m1,m2"        reviewer chain (default: a cheap model per provider)
DEFAULT_REVIEW_MODELS = {
    # Flash Lite: checking needs reading, not writing — and Lite has 500 requests/day (vs 20 for
    # Flash), so reviews never eat the writers' daily budget
    "google":    ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"],
    "anthropic": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
}


def review_enabled():
    return os.environ.get("QUEST_REVIEW", "1").strip().lower() not in ("0", "false", "no", "off")


def review_provider(default=None):
    p = os.environ.get("QUEST_REVIEW_PROVIDER", "").strip().lower()
    if p in ("google", "gemini"):
        return "google"
    if p in ("anthropic", "claude"):
        return "anthropic"
    return default or gen_provider()


def review_models(provider):
    chain = os.environ.get("QUEST_REVIEW_MODELS", "").strip()
    if chain:
        return [m.strip() for m in chain.split(",") if m.strip()]
    return list(DEFAULT_REVIEW_MODELS.get(provider, []))


def run_review(story, provider=None, usage_sink=None, log=None, call=None):
    """Review a story dict for continuity. Returns narrative_review's result dict
    (status OK | REVIEW | skipped). `call(system, messages) -> text` is injectable for tests."""
    if call is None:
        provider = review_provider(provider)
        models, key = review_models(provider), env_api_key(provider)
        if not key or not models:
            return {"status": "skipped", "issues": [], "majors": 0, "minors": 0,
                    "detail": f"no {provider} key/model for the review"}

        def call(system, messages):
            text, _used = call_with_fallback(provider, models, system, messages, key,
                                             log=log, usage_sink=usage_sink)
            return text
    return NR.review_story(story, call, log)


def gate_report(path, difficulty):
    """Run ALL three gates on a story file. Returns (all_ok, feedback_lines, summary_dict)."""
    story = load_story_file(path)
    problems = validate_story_dict(story)
    coh_ok, coh_items = coherence_check(path)
    verdict, bal_lines = balance_check(path, difficulty)
    ok = (not problems) and coh_ok and (verdict == "PASS")
    feedback = []
    if problems:
        feedback.append("CORRECTNESS — fix broken links / reachability: " + "; ".join(problems[:20]))
    if not coh_ok:
        feedback.append("COHERENCE — the map/opening needs work: " + "  ".join(coh_items[:20]))
    if verdict != "PASS":
        feedback.append(f"BALANCE — '{difficulty}' target not met ({verdict}): " + "; ".join(bal_lines[:8]))
    summary = {"correctness": not problems, "coherence": coh_ok,
               "balance": verdict, "bal_lines": bal_lines}
    return ok, feedback, summary


def create_story(*args, **kwargs):
    """Draft a story and iterate draft → validate → coherence → balance → story review until
    every gate passes, then save it — see _create_story for the arguments and return value.
    Also records how many writer/review calls the run took (quota.py uses the average to tell
    players how many more stories today's free tier allows)."""
    stats = {"writer": 0, "review": 0}
    result = None
    try:
        result = _create_story(*args, _stats=stats, **kwargs)
        return result
    finally:
        if kwargs.get("model_call") is None and (stats["writer"] or stats["review"]):
            try:
                cost = (result[2] or {}).get("cost_usd", 0.0) if result else 0.0
                Q.record_run(stats["writer"], stats["review"], cost)
            except Exception:
                pass


def _create_story(theme, difficulty, length=14, title="", api_key=None, provider=None,
                  models=None, out_path=None, max_attempts=6, model_call=None, log=None,
                  keep_best=False, language="English", language_level="C2",
                  review=None, review_call=None, _stats=None):
    """Draft a story and iterate draft → validate → coherence → balance → story review until
    EVERY gate passes, then save it. Returns (ok, saved_path_or_None, summary).

    The review gate (narrative_review.py) runs only once the three free gates pass; its major
    findings go back into the repair loop. `review=None` follows QUEST_REVIEW (on by default);
    `review_call(system, messages) -> text` is injectable for tests.

    On full success a clean story is saved and ok=True. If no attempt passes within the budget
    (or every model hits its free-tier limit) and `keep_best=True`, the best draft so far is
    saved with `draft: true` + a `gate_summary` so the work isn't lost — returned as
    (False, draft_path, summary-with-'draft':True). With keep_best=False, failure returns
    (False, None, summary). Free-tier-safe via the model fallback chain.

    `model_call(system, messages) -> text` is injectable for tests; by default it calls the
    provider with the fallback chain."""
    log = log or (lambda *a: None)
    provider = provider or gen_provider()
    models = models or gen_models(provider)
    if api_key is None:
        api_key = env_api_key(provider)
    system, user = build_prompts(theme, difficulty, length, title, language, language_level)
    usage = []   # per-call token usage across attempts, for cost reporting
    if model_call is None:
        def model_call(system, messages):
            text, _used = call_with_fallback(provider, models, system, messages, api_key,
                                             log=log, usage_sink=usage)
            return text

    do_review = review_enabled() if review is None else bool(review)

    def _score(s):
        return (int(s["correctness"]) + int(s["coherence"]) + int(s["balance"] == "PASS")
                + int(s.get("review") in ("OK", "skipped", "off")))

    def _attach_usage(summary):
        """Merge accumulated token/cost totals into a returned summary dict."""
        info = {"tokens_in":  sum(u["input_tokens"] for u in usage),
                "tokens_out": sum(u["output_tokens"] for u in usage),
                "cost_usd":   round(sum(u["cost_usd"] for u in usage), 6),
                "model_used": (usage[-1]["model"] if usage else ""),
                "attempts":   len(usage)}
        if isinstance(summary, dict):
            out = dict(summary); out.update(info); return out
        return info

    messages = [{"role": "user", "content": user}]
    tmp = tempfile.NamedTemporaryFile(prefix="story_engine_", suffix=".json", delete=False).name
    best = None          # (score, story_dict, summary)
    limit_error = None
    try:
        for attempt in range(1, max_attempts + 1):
            log(f"[{attempt}/{max_attempts}] drafting …")
            if _stats is not None:
                _stats["writer"] += 1
            try:
                text = model_call(system, messages)
            except Exception as e:               # model/provider unavailable (e.g. all limits hit)
                limit_error = e
                log(f"    ! model unavailable — stopping: {str(e)[:120]}")
                break
            story, perr = extract_json(text)
            if story is None:
                log(f"    ✗ unparseable JSON ({perr})")
                messages += [{"role": "assistant", "content": text or ""},
                             {"role": "user", "content": f"{perr}. Resend ONLY the complete corrected JSON object."}]
                continue
            save_story_file(story, tmp)
            ok, feedback, summary = gate_report(tmp, difficulty)
            summary["review"] = "off" if not do_review else "not run"
            log(f"    validate:{'OK' if summary['correctness'] else 'FAIL'}  "
                f"coherence:{'OK' if summary['coherence'] else 'REVIEW'}  balance:{summary['balance']}")
            if ok and do_review:                     # 4th gate — only for otherwise-green drafts
                if _stats is not None:
                    _stats["review"] += 1
                rv = run_review(story, provider=provider, usage_sink=usage, log=log, call=review_call)
                summary["review"], summary["review_issues"] = rv["status"], rv["issues"]
                log(f"    story review:{rv['status']} ({rv['detail']})")
                if rv["status"] == "REVIEW":
                    ok = False
                    feedback = ["NARRATIVE — the story review found continuity problems; fix every "
                                "major one (and the minor ones if easy): " + " | ".join(NR.feedback_lines(rv))]
            if best is None or _score(summary) >= best[0]:
                best = (_score(summary), story, summary)
            if ok:
                final = out_path or unique_story_path(story.get("title") or theme)
                save_story_file(story, final)
                log(f"    ✓ all gates green — saved to {final}")
                return True, final, _attach_usage(summary)
            messages += [{"role": "assistant", "content": json.dumps(story)},
                         {"role": "user", "content":
                          "Your story did NOT pass all gates. Fix EVERY item below and resend ONLY the "
                          "full corrected JSON. Keep the same theme and difficulty.\n- " + "\n- ".join(feedback)}]
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    # no attempt passed every gate
    if keep_best and best is not None:
        _, story, summary = best
        draft = dict(story)
        draft["draft"] = True
        draft["gate_summary"] = {k: summary.get(k) for k in ("correctness", "coherence", "balance", "review")}
        path = out_path or unique_story_path((story.get("title") or theme) + " draft")
        save_story_file(draft, path)
        log(f"    saved best draft to {path} (did not pass all gates)")
        result = dict(summary)
        result["draft"] = True
        if limit_error:
            result["limit_error"] = str(limit_error)
        return False, path, _attach_usage(result)
    if limit_error and best is None:
        raise limit_error                         # nothing usable produced and the API was down
    return False, None, _attach_usage(best[2] if best else None)
